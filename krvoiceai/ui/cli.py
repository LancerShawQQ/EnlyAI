"""命令行界面"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..app import KrVoiceAI
from ..core.logger import get_logger


def main():
    parser = argparse.ArgumentParser(
        prog="krvoiceai",
        description="KrVoiceAI - 虚拟人口播智能体",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # run - 运行任务
    p_run = sub.add_parser("run", help="运行口播视频生成任务")
    p_run.add_argument("script", nargs="?", default="", help="口播文案")
    p_run.add_argument("--url", help="参考视频 URL（用于文案提取）")
    p_run.add_argument("--avatar", default="default", help="数字人形象 ID")
    p_run.add_argument("--voice", default="default", help="音色 ID")
    p_run.add_argument("--mode", default="polish",
                       choices=["polish", "rewrite", "generate"],
                       help="文案处理模式")
    p_run.add_argument("--platform", default="douyin",
                       help="目标平台")
    p_run.add_argument("--publish", action="store_true", help="自动发布")
    p_run.add_argument("--file", help="从文件读取文案")

    # job - 任务管理
    p_job = sub.add_parser("job", help="任务管理")
    job_sub = p_job.add_subparsers(dest="job_command")
    job_sub.add_parser("list", help="列出任务")
    p_status = job_sub.add_parser("status", help="查看任务状态")
    p_status.add_argument("job_id")
    p_rerun = job_sub.add_parser("rerun", help="重跑任务")
    p_rerun.add_argument("job_id")

    # avatar - 形象管理
    p_avatar = sub.add_parser("avatar", help="数字人形象管理")
    avatar_sub = p_avatar.add_subparsers(dest="avatar_command")
    avatar_sub.add_parser("list", help="列出形象")
    p_reg_avatar = avatar_sub.add_parser("register", help="注册形象")
    p_reg_avatar.add_argument("avatar_id", help="形象 ID")
    p_reg_avatar.add_argument("video", help="参考视频路径")

    # voice - 音色管理
    p_voice = sub.add_parser("voice", help="音色管理")
    voice_sub = p_voice.add_subparsers(dest="voice_command")
    voice_sub.add_parser("list", help="列出音色")
    p_reg_voice = voice_sub.add_parser("register", help="注册音色")
    p_reg_voice.add_argument("voice_id", help="音色 ID")
    p_reg_voice.add_argument("audio", help="样本音频路径")

    # serve - 启动 Web UI
    p_serve = sub.add_parser("serve", help="启动 Web UI")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=7860)

    # health - 健康检查
    sub.add_parser("health", help="系统健康检查")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    app = KrVoiceAI()
    logger = get_logger()

    if args.command == "run":
        script = args.script
        if args.file:
            script = Path(args.file).read_text(encoding="utf-8")
        if not script and not args.url:
            print("错误：需要提供文案或参考视频 URL")
            return 1
        print(f"提交任务: avatar={args.avatar} voice={args.voice} mode={args.mode}")
        result = app.submit_and_run(
            script=script,
            reference_video_url=args.url,
            avatar_id=args.avatar,
            voice_id=args.voice,
            script_mode=args.mode,
            platform=args.platform,
            auto_publish=args.publish,
        )
        print(f"\n任务 ID: {result['job_id']}")
        print(f"状态: {result['status']}")
        if result["success"]:
            out = result["output"]
            print(f"最终视频: {out.get('final_video', '无')}")
            print(f"标题: {out.get('title', '无')}")
        else:
            print(f"失败: {result.get('error', '未知错误')}")
        return 0 if result["success"] else 1

    elif args.command == "job":
        if args.job_command == "list":
            jobs = app.list_jobs()
            if not jobs:
                print("暂无任务")
            for j in jobs:
                print(f"  {j['job_id']}  {j['status']}  {j.get('created_at', '')}")
        elif args.job_command == "status":
            job = app.get_job(args.job_id)
            if not job:
                print(f"任务不存在: {args.job_id}")
                return 1
            print(json.dumps(job, ensure_ascii=False, indent=2, default=str))
        elif args.job_command == "rerun":
            success = app.rerun_job(args.job_id)
            print(f"重跑结果: {'成功' if success else '失败'}")
            return 0 if success else 1

    elif args.command == "avatar":
        if args.avatar_command == "list":
            avatars = app.list_avatars()
            if not avatars:
                print("暂无形象")
            for a in avatars:
                print(f"  {a['avatar_id']}")
        elif args.avatar_command == "register":
            ok = app.register_avatar(args.avatar_id, Path(args.video))
            print(f"注册形象: {'成功' if ok else '失败'}")
            return 0 if ok else 1

    elif args.command == "voice":
        if args.voice_command == "list":
            voices = app.list_voices()
            if not voices:
                print("暂无音色")
            for v in voices:
                print(f"  {v['voice_id']}")
        elif args.voice_command == "register":
            ok = app.register_voice(args.voice_id, Path(args.audio))
            print(f"注册音色: {'成功' if ok else '失败'}")
            return 0 if ok else 1

    elif args.command == "serve":
        from .gradio_app import launch
        launch(host=args.host, port=args.port)

    elif args.command == "health":
        info = app.health_check()
        print(json.dumps(info, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
