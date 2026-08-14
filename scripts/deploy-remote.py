#!/usr/bin/env python3
"""
Deploy EnlyAI to Alibaba Cloud ECS via SSH (paramiko).
Handles all known pitfalls: symlinks, native binaries, node_modules.
Usage: python3 scripts/deploy-remote.py
"""
import paramiko
import os
import subprocess
import sys
import time
import tempfile

HOST = os.getenv("DEPLOY_SSH_HOST", "114.215.183.45")
USER = os.getenv("DEPLOY_SSH_USER", "root")
PASS = os.getenv("DEPLOY_SSH_PASSWORD")
PORT = int(os.getenv("DEPLOY_SSH_PORT", "22"))
CHUNK_SIZE = 256 * 1024
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POST_DEPLOY_BASE_URL = os.getenv("POST_DEPLOY_BASE_URL", "https://www.enlyai.com")
SKIP_POST_DEPLOY_E2E = os.getenv("DEPLOY_SKIP_POST_E2E") == "1"

_tmp = tempfile.gettempdir()
FILES = [
    (os.path.join(_tmp, "enlyai-standalone.tgz"), "/tmp/enlyai-standalone.tgz"),
    (os.path.join(_tmp, "enlyai-static.tgz"), "/tmp/enlyai-static.tgz"),
    (os.path.join(_tmp, "enlyai-public.tgz"), "/tmp/enlyai-public.tgz"),
]

# All paths where better-sqlite3 looks for its native binary
NATIVE_BIN_PATHS = [
    "node_modules/better-sqlite3/build/Release/better_sqlite3.node",
    "node_modules/better-sqlite3/build/Debug/better_sqlite3.node",
    "node_modules/better-sqlite3/build/default/better_sqlite3.node",
    "node_modules/better-sqlite3/out/Release/better_sqlite3.node",
    "node_modules/better-sqlite3/out/Debug/better_sqlite3.node",
    "node_modules/better-sqlite3/Release/better_sqlite3.node",
    "node_modules/better-sqlite3/Debug/better_sqlite3.node",
    "node_modules/better-sqlite3/compiled/22.22.0/linux/x64/better_sqlite3.node",
    "node_modules/better-sqlite3/lib/binding/node-v127-linux-x64/better_sqlite3.node",
    "node_modules/better-sqlite3/addon-build/release/install-root/better_sqlite3.node",
    "node_modules/better-sqlite3/addon-build/debug/install-root/better_sqlite3.node",
    "node_modules/better-sqlite3/addon-build/default/install-root/better_sqlite3.node",
]

DEPLOY_SCRIPT = r"""
set -e

RELEASE="/opt/enlyai/releases/$(date +%Y%m%d_%H%M%S)"
APP="${RELEASE}/.next/standalone"
PREV=$(readlink /opt/enlyai/current)
SHARED_DATA="/opt/enlyai/shared/data"

echo "=== Creating release ${RELEASE} ==="
mkdir -p "${APP}"

echo "=== Extracting files ==="
tar --warning=no-unknown-keyword --ignore-zeros -xzf /tmp/enlyai-standalone.tgz -C "${APP}"
mkdir -p "${APP}/.next/static"
tar --warning=no-unknown-keyword --ignore-zeros -xzf /tmp/enlyai-static.tgz -C "${APP}/.next/static"
mkdir -p "${APP}/public"
tar --warning=no-unknown-keyword --ignore-zeros -xzf /tmp/enlyai-public.tgz -C "${APP}/public"

echo "=== Fixing native binary (better-sqlite3) ==="
if [ -n "${PREV}" ]; then
    PREV_BIN=$(find "${PREV}" -name "better_sqlite3.node" -exec file {} \; 2>/dev/null | grep ELF | head -1 | cut -d: -f1)
    if [ -n "${PREV_BIN}" ]; then
        echo "Found ELF binary: ${PREV_BIN}"
        file "${PREV_BIN}"
        # Copy to top-level node_modules/better-sqlite3 paths
        for P in \
            "node_modules/better-sqlite3/build/Release" \
            "node_modules/better-sqlite3/build/Debug" \
            "node_modules/better-sqlite3/build/default" \
            "node_modules/better-sqlite3/out/Release" \
            "node_modules/better-sqlite3/out/Debug" \
            "node_modules/better-sqlite3/Release" \
            "node_modules/better-sqlite3/Debug" \
            "node_modules/better-sqlite3/compiled/22.22.0/linux/x64" \
            "node_modules/better-sqlite3/lib/binding/node-v127-linux-x64" \
            "node_modules/better-sqlite3/addon-build/release/install-root" \
            "node_modules/better-sqlite3/addon-build/debug/install-root" \
            "node_modules/better-sqlite3/addon-build/default/install-root" \
        ; do
            mkdir -p "${APP}/${P}"
            cp -f "${PREV_BIN}" "${APP}/${P}/better_sqlite3.node"
        done
        # Also copy to ALL better-sqlite3 directories inside .next/node_modules
        # (pnpm hoists modules under hashed directory names like better-sqlite3-<hash>)
        for BSDIR in $(find "${APP}/.next/node_modules" -maxdepth 1 -type d -name "better-sqlite3*" 2>/dev/null); do
            for P in \
                "build/Release" "build/Debug" "build/default" \
                "out/Release" "out/Debug" "Release" "Debug" \
                "compiled/22.22.0/linux/x64" \
                "lib/binding/node-v127-linux-x64" \
                "addon-build/release/install-root" \
                "addon-build/debug/install-root" \
                "addon-build/default/install-root" \
            ; do
                mkdir -p "${BSDIR}/${P}"
                cp -f "${PREV_BIN}" "${BSDIR}/${P}/better_sqlite3.node"
            done
            echo "  Fixed: ${BSDIR}"
        done
        # Also fix inside .pnpm store if present
        for PNPM_DIR in $(find "${APP}/node_modules/.pnpm" -maxdepth 3 -type d -name "better-sqlite3" 2>/dev/null); do
            for P in \
                "build/Release" "build/Debug" "build/default" \
                "out/Release" "out/Debug" "Release" "Debug" \
                "compiled/22.22.0/linux/x64" \
                "lib/binding/node-v127-linux-x64" \
                "addon-build/release/install-root" \
                "addon-build/debug/install-root" \
                "addon-build/default/install-root" \
            ; do
                mkdir -p "${PNPM_DIR}/${P}"
                cp -f "${PREV_BIN}" "${PNPM_DIR}/${P}/better_sqlite3.node"
            done
            echo "  Fixed pnpm: ${PNPM_DIR}"
        done
        echo "Native binary OK"
    else
        echo "WARNING: No ELF binary found in previous release"
    fi
else
    echo "WARNING: No previous release found"
fi

echo "=== Fixing top-level node_modules symlinks ==="
if [ -n "${PREV}" ] && [ -d "${PREV}/.next/standalone/node_modules" ]; then
    PREV_NM="${PREV}/.next/standalone/node_modules"
    cd "${PREV_NM}"
    COPIED=0
    for item in *; do
        if [ "$item" = ".pnpm" ] || [ "$item" = ".modules.yaml" ]; then
            continue
        fi
        if [ ! -e "${APP}/node_modules/$item" ] && [ ! -L "${APP}/node_modules/$item" ]; then
            cp -a "$item" "${APP}/node_modules/$item"
            COPIED=$((COPIED + 1))
        fi
    done
    echo "Copied ${COPIED} top-level modules from previous release"
else
    echo "WARNING: No previous node_modules to copy from"
fi

echo "=== Fixing pnpm top-level symlinks for required packages ==="
cd "${APP}/node_modules"
# Scan .pnpm store and create top-level symlinks for any packages that
# Next.js needs at runtime but pnpm didn't hoist to the top level.
FIXED=0
for PNPM_PKG_DIR in .pnpm/@*+*; do
    [ -d "${PNPM_PKG_DIR}/node_modules" ] || continue
    for PKG in "${PNPM_PKG_DIR}/node_modules/"@*/*; do
        [ -e "${PKG}" ] || continue
        PKG_BASENAME=$(basename "${PKG}")
        PKG_SCOPE=$(basename "$(dirname "${PKG}")")
        TARGET="${PKG_SCOPE}/${PKG_BASENAME}"
        if [ ! -e "${TARGET}" ]; then
            mkdir -p "${PKG_SCOPE}"
            ln -sfn "${APP}/node_modules/${PNPM_PKG_DIR}/node_modules/${TARGET}" "${TARGET}"
            FIXED=$((FIXED + 1))
        fi
    done
done
for PNPM_PKG_DIR in .pnpm/*+*; do
    [ -d "${PNPM_PKG_DIR}/node_modules" ] || continue
    for PKG in "${PNPM_PKG_DIR}/node_modules/"*; do
        [ -e "${PKG}" ] || continue
        PKG_BASENAME=$(basename "${PKG}")
        if [ ! -e "${PKG_BASENAME}" ]; then
            ln -sfn "${APP}/node_modules/${PNPM_PKG_DIR}/node_modules/${PKG_BASENAME}" "${PKG_BASENAME}"
            FIXED=$((FIXED + 1))
        fi
    done
done
echo "Fixed ${FIXED} pnpm top-level symlinks"

echo "=== Copying .next/node_modules ==="
if [ -n "${PREV}" ] && [ -d "${PREV}/.next/standalone/.next/node_modules" ]; then
    mkdir -p "${APP}/.next/node_modules"
    cp -a "${PREV}/.next/standalone/.next/node_modules/"* "${APP}/.next/node_modules/" 2>/dev/null || true
    echo "Copied .next/node_modules"
fi

echo "=== Setting up data and env ==="
rm -rf "${APP}/data"
ln -sfn "${SHARED_DATA}" "${APP}/data"
# Copy .env.local from shared location if it exists (for non-systemd deployments)
if [ -f "/opt/enlyai/shared/.env.local" ]; then
    cp -f "/opt/enlyai/shared/.env.local" "${APP}/.env.local"
    echo "Copied .env.local from shared"
fi
# Copy server-providers.yml from shared location (LLM provider config with API keys)
if [ -f "/opt/enlyai/shared/server-providers.yml" ]; then
    cp -f "/opt/enlyai/shared/server-providers.yml" "${APP}/server-providers.yml"
    echo "Copied server-providers.yml from shared"
fi

echo "=== Verification ==="
PASS=0
FAIL=0

test -d "${APP}/.next/static/chunks" && { echo "  [OK] static chunks"; PASS=$((PASS+1)); } || { echo "  [FAIL] static chunks"; FAIL=$((FAIL+1)); }
test -f "${APP}/server.js" && { echo "  [OK] server.js"; PASS=$((PASS+1)); } || { echo "  [FAIL] server.js"; FAIL=$((FAIL+1)); }
test -f "${APP}/custom-server.mjs" && { echo "  [OK] custom-server.mjs"; PASS=$((PASS+1)); } || { echo "  [FAIL] custom-server.mjs"; FAIL=$((FAIL+1)); }
test -f "${APP}/classroom-websocket.cjs" && { echo "  [OK] classroom-websocket.cjs"; PASS=$((PASS+1)); } || { echo "  [FAIL] classroom-websocket.cjs"; FAIL=$((FAIL+1)); }
test -f "${APP}/node_modules/better-sqlite3/build/Release/better_sqlite3.node" && { echo "  [OK] native binary"; PASS=$((PASS+1)); } || { echo "  [FAIL] native binary"; FAIL=$((FAIL+1)); }
test -f "${APP}/node_modules/styled-jsx/package.json" && { echo "  [OK] styled-jsx"; PASS=$((PASS+1)); } || { echo "  [FAIL] styled-jsx"; FAIL=$((FAIL+1)); }
ls -la "${APP}/data" > /dev/null 2>&1 && { echo "  [OK] data symlink"; PASS=$((PASS+1)); } || { echo "  [FAIL] data symlink"; FAIL=$((FAIL+1)); }

echo "Passed: ${PASS}, Failed: ${FAIL}"

echo "=== Switching current ==="
ln -sfn "${RELEASE}" /opt/enlyai/current

echo "=== Ensuring systemd uses custom WebSocket server ==="
cat >/etc/systemd/system/enlyai.service <<'SERVICEEOF'
[Unit]
Description=EnlyAI Classroom
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/enlyai/current/.next/standalone
Environment=NODE_ENV=production
Environment=HOSTNAME=0.0.0.0
Environment=PORT=8000
EnvironmentFile=-/opt/enlyai/shared/.env.local
ExecStart=/usr/local/bin/node /opt/enlyai/current/.next/standalone/custom-server.mjs
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICEEOF
systemctl daemon-reload
systemctl enable enlyai.service >/dev/null 2>&1 || true

echo "=== Restarting service ==="
systemctl restart enlyai.service

echo "=== Waiting for startup ==="
sleep 12

if curl -fsS http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    echo "  [OK] Health check PASSED"
else
    echo "  [FAIL] Health check FAILED"
    journalctl -u enlyai.service --no-pager -n 20
fi

echo "=== Cleanup old releases (keep 3) ==="
cd /opt/enlyai/releases
ls -td 2* | tail -n +4 | xargs rm -rf 2>/dev/null || true

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo "Release: ${RELEASE}"
echo "URL: https://www.enlyai.com"
"""


def connect():
    t = paramiko.Transport((HOST, PORT))
    t.connect(username=USER, password=PASS)
    t.set_keepalive(30)
    t.default_window_size = 2147483647
    t.packetizer.REKEY_BYTES = 2147483647
    t.packetizer.REKEY_PACKETS = 2147483647
    client = paramiko.SSHClient()
    client._transport = t
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def upload_file(sftp, local_path, remote_path):
    local_size = os.path.getsize(local_path)
    try:
        remote_size = sftp.stat(remote_path).st_size
    except IOError:
        remote_size = 0

    if remote_size == local_size:
        print(f"  Remote file has the same size ({local_size // 1024 // 1024}MB), re-uploading")
    sftp.put(local_path, remote_path)
    uploaded_size = sftp.stat(remote_path).st_size
    if uploaded_size != local_size:
        raise RuntimeError(
            f"Upload size mismatch for {remote_path}: local={local_size}, remote={uploaded_size}"
        )
    print(f"  Uploaded {local_size // 1024 // 1024}MB")


def run_remote(client, cmd, timeout=300):
    transport = client.get_transport()
    channel = transport.open_session()
    channel.settimeout(timeout)
    channel.set_combine_stderr(True)
    channel.exec_command(cmd)

    while True:
        if channel.recv_ready():
            data = channel.recv(8192)
            if not data:
                break
            text = data.decode("utf-8", errors="replace")
            sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        if channel.exit_status_ready():
            while channel.recv_ready():
                data = channel.recv(8192)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            break
        time.sleep(0.1)

    return channel.recv_exit_status()


def run_post_deploy_e2e():
    if SKIP_POST_DEPLOY_E2E:
        print("\n=== Skipping post-deploy voice e2e (DEPLOY_SKIP_POST_E2E=1) ===")
        return 0

    env = os.environ.copy()
    env["PLAYWRIGHT_BASE_URL"] = POST_DEPLOY_BASE_URL
    env["PLAYWRIGHT_SKIP_WEBSERVER"] = "1"

    print("\n=== Running post-deploy production voice e2e ===")
    print(f"Base URL: {POST_DEPLOY_BASE_URL}")
    result = subprocess.run(
        ["pnpm", "run", "test:e2e:deployed:voice"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    return result.returncode


def main():
    if any(arg in {'-h', '--help'} for arg in sys.argv[1:]):
        print(__doc__.strip())
        return 0

    if not PASS:
        print("ERROR: DEPLOY_SSH_PASSWORD environment variable not set")
        return 1

    for attempt in range(1, 4):
        print(f"\n{'=' * 60}")
        print(f"Attempt {attempt}/3")
        print(f"{'=' * 60}")
        try:
            print(f"Connecting to {HOST}...")
            client = connect()
            print("Connected!")

            sftp = client.open_sftp()

            for local, remote in sorted(FILES, key=lambda x: os.path.getsize(x[0])):
                size = os.path.getsize(local)
                print(f"\nUploading {os.path.basename(local)} ({size // 1024 // 1024}MB)...")
                upload_file(sftp, local, remote)

            sftp.close()
            print("\nAll files uploaded!")

            print("\n=== Running deployment ===\n")
            rc = run_remote(client, DEPLOY_SCRIPT, timeout=300)
            print(f"\nExit code: {rc}")
            client.close()
            if rc != 0:
                return rc

            post_rc = run_post_deploy_e2e()
            if post_rc != 0:
                print(f"\nPost-deploy voice e2e failed with exit code: {post_rc}")
                return post_rc

            return 0

        except Exception as e:
            print(f"\nError: {e}")
            try:
                client.close()
            except Exception:
                pass
            if attempt < 3:
                print(f"Retrying in {attempt * 5}s...")
                time.sleep(attempt * 5)
            else:
                print("All retries exhausted!")
                return 1


if __name__ == "__main__":
    sys.exit(main())
