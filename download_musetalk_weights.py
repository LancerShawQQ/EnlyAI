"""Download MuseTalk model weights from HuggingFace (using mirror)."""
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from huggingface_hub import snapshot_download
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "MuseTalk" / "models"

repos = [
    # MuseTalk unet + config
    {
        "repo_id": "TMElyralab/MuseTalk",
        "local_dir": str(MODELS_DIR),
        "allow_patterns": ["musetalkV15/unet.pth", "musetalkV15/musetalk.json"],
    },
    # SD VAE
    {
        "repo_id": "stabilityai/sd-vae-ft-mse",
        "local_dir": str(MODELS_DIR / "sd-vae"),
        "allow_patterns": ["config.json", "diffusion_pytorch_model.bin"],
    },
    # Whisper tiny (for audio feature extraction)
    {
        "repo_id": "openai/whisper-tiny",
        "local_dir": str(MODELS_DIR / "whisper"),
        "allow_patterns": ["config.json", "pytorch_model.bin", "preprocessor_config.json"],
    },
    # face-parse-bisent (for face parsing/blending)
    {
        "repo_id": "ManyOtherFunctions/face-parse-bisent",
        "local_dir": str(MODELS_DIR / "face-parse-bisent"),
        "allow_patterns": ["79999_iter.pth", "resnet18-5c106cde.pth"],
    },
]

for i, repo in enumerate(repos):
    print(f"[{i+1}/{len(repos)}] Downloading {repo['repo_id']} -> {repo['local_dir']} ...")
    snapshot_download(
        repo_id=repo["repo_id"],
        local_dir=repo["local_dir"],
        allow_patterns=repo["allow_patterns"],
    )
    print(f"      Done.")

# Verify all files exist
required = [
    MODELS_DIR / "musetalkV15" / "unet.pth",
    MODELS_DIR / "musetalkV15" / "musetalk.json",
    MODELS_DIR / "sd-vae" / "diffusion_pytorch_model.bin",
    MODELS_DIR / "sd-vae" / "config.json",
    MODELS_DIR / "whisper" / "pytorch_model.bin",
    MODELS_DIR / "whisper" / "config.json",
    MODELS_DIR / "face-parse-bisent" / "79999_iter.pth",
    MODELS_DIR / "face-parse-bisent" / "resnet18-5c106cde.pth",
]
print("\n=== Verification ===")
all_ok = True
for f in required:
    if f.exists():
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  OK  {f.relative_to(MODELS_DIR)} ({size_mb:.1f} MB)")
    else:
        print(f"  MISSING  {f.relative_to(MODELS_DIR)}")
        all_ok = False

if all_ok:
    print("\n[OK] All MuseTalk weights downloaded successfully!")
else:
    print("\n[FAIL] Some weights are missing!")
