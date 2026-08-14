"""生成 EnlyAI 报名帖封面图 - HTML to PNG (v2: 居中+丰富配色)"""
import asyncio
from pathlib import Path

async def main():
    from playwright.async_api import async_playwright

    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; overflow: hidden; }
.cover {
  width: 1280px; height: 720px;
  background:
    radial-gradient(ellipse at 25% 30%, #1a1040 0%, transparent 50%),
    radial-gradient(ellipse at 75% 70%, #0a2040 0%, transparent 50%),
    radial-gradient(ellipse at 50% 50%, #0d1530 0%, #03050e 80%);
  position: relative; display: flex; align-items: center; justify-content: center;
  font-family: -apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif;
}
/* 网格背景 */
.grid-bg {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(100,180,255,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(100,180,255,0.05) 1px, transparent 1px);
  background-size: 40px 40px;
  -webkit-mask: radial-gradient(ellipse 80% 70% at center, black 20%, transparent 90%);
          mask: radial-gradient(ellipse 80% 70% at center, black 20%, transparent 90%);
}
/* 多色光晕 */
.glow1 { position: absolute; top: -100px; right: -60px; width: 450px; height: 450px;
  background: radial-gradient(circle, rgba(0,180,255,0.2), transparent 65%); border-radius: 50%; }
.glow2 { position: absolute; bottom: -120px; left: -80px; width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(140,80,255,0.15), transparent 65%); border-radius: 50%; }
.glow3 { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
  width: 700px; height: 300px;
  background: radial-gradient(ellipse, rgba(255,100,150,0.08), transparent 70%); }
/* 装饰圆环 */
.rings { position: absolute; left: 50%; top: 50%; transform: translate(-50%,-50%);
  width: 650px; height: 650px; z-index: 1; }
/* 中央内容 */
.content { position: relative; z-index: 10; text-align: center; color: #fff;
  padding: 0 80px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.tag { display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 20px; border: 1px solid rgba(0,200,255,0.35);
  border-radius: 24px; font-size: 14px; color: #5ec8ff; letter-spacing: 3px;
  margin-bottom: 28px; background: rgba(0,100,200,0.08);
  backdrop-filter: blur(10px); }
.tag-dot { width: 6px; height: 6px; background: #5ec8ff; border-radius: 50%;
  box-shadow: 0 0 8px #5ec8ff; }
.title { font-size: 76px; font-weight: 800; letter-spacing: -2px; line-height: 1;
  background: linear-gradient(135deg, #ffffff 0%, #6db8ff 50%, #b88aff 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 14px; text-shadow: 0 0 60px rgba(100,180,255,0.3); }
.subtitle { font-size: 26px; font-weight: 300; color: rgba(255,255,255,0.65);
  margin-bottom: 36px; letter-spacing: 1px; }
/* 流水线 */
.pipeline { display: flex; align-items: center; justify-content: center; gap: 6px; flex-wrap: wrap; max-width: 900px; }
.step { padding: 7px 14px; border-radius: 8px; font-size: 13px; font-weight: 500;
  border: 1px solid; }
.step:nth-child(1) { background: rgba(255,100,100,0.1); border-color: rgba(255,100,100,0.3); color: #ff8888; }
.step:nth-child(3) { background: rgba(255,180,80,0.1); border-color: rgba(255,180,80,0.3); color: #ffc070; }
.step:nth-child(5) { background: rgba(100,255,150,0.1); border-color: rgba(100,255,150,0.3); color: #66dd99; }
.step:nth-child(7) { background: rgba(80,200,255,0.1); border-color: rgba(80,200,255,0.3); color: #5ec8ff; }
.step:nth-child(9) { background: rgba(180,130,255,0.1); border-color: rgba(180,130,255,0.3); color: #bb88ff; }
.step:nth-child(11) { background: rgba(255,120,200,0.1); border-color: rgba(255,120,200,0.3); color: #ff88cc; }
.step:nth-child(13) { background: rgba(255,200,100,0.1); border-color: rgba(255,200,100,0.3); color: #ffcc66; }
.arrow { color: rgba(255,255,255,0.25); font-size: 14px; }
/* 底部信息 */
.footer { position: absolute; bottom: 36px; left: 0; right: 0; text-align: center; z-index: 10; }
.features { display: flex; justify-content: center; gap: 48px; }
.feature { font-size: 15px; color: rgba(255,255,255,0.45); display: flex; align-items: center; gap: 8px; }
.feature-icon { width: 8px; height: 8px; border-radius: 2px; }
.feature:nth-child(1) .feature-icon { background: #ff8888; box-shadow: 0 0 6px #ff8888; }
.feature:nth-child(2) .feature-icon { background: #5ec8ff; box-shadow: 0 0 6px #5ec8ff; }
.feature:nth-child(3) .feature-icon { background: #bb88ff; box-shadow: 0 0 6px #bb88ff; }
.feature strong { color: rgba(255,255,255,0.85); font-weight: 600; }
</style></head>
<body>
<div class="cover">
  <div class="grid-bg"></div>
  <div class="glow1"></div>
  <div class="glow2"></div>
  <div class="glow3"></div>
  <svg class="rings" viewBox="0 0 650 650">
    <circle cx="325" cy="325" r="310" fill="none" stroke="rgba(100,180,255,0.06)" stroke-width="1"/>
    <circle cx="325" cy="325" r="250" fill="none" stroke="rgba(180,130,255,0.06)" stroke-width="1"/>
    <circle cx="325" cy="325" r="190" fill="none" stroke="rgba(255,100,150,0.05)" stroke-width="1"/>
    <circle cx="325" cy="325" r="130" fill="none" stroke="rgba(100,180,255,0.05)" stroke-width="1"/>
  </svg>
  <div class="content">
    <div class="tag"><span class="tag-dot"></span>AI 主理人出道计划</div>
    <div class="title">EnlyAI</div>
    <div class="subtitle">虚拟人口播智能体 · 10分钟生成商用级口播视频</div>
    <div class="pipeline">
      <span class="step">文案提取</span><span class="arrow">›</span>
      <span class="step">声音克隆</span><span class="arrow">›</span>
      <span class="step">唇形同步</span><span class="arrow">›</span>
      <span class="step">字幕</span><span class="arrow">›</span>
      <span class="step">B-roll</span><span class="arrow">›</span>
      <span class="step">合成</span><span class="arrow">›</span>
      <span class="step">一键发布</span>
    </div>
  </div>
  <div class="footer">
    <div class="features">
      <span class="feature"><span class="feature-icon"></span><strong>本地运行</strong> 隐私可控</span>
      <span class="feature"><span class="feature-icon"></span><strong>Wav2Lip GPU</strong> 商用级唇形同步</span>
      <span class="feature"><span class="feature-icon"></span><strong>4平台</strong> 一键发布</span>
    </div>
  </div>
</div>
</body></html>"""

    output = Path(r"D:\cursor_project\koubo\KrVoiceAI\docs\contest\cover_enlyai_final.png")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=str(output), full_page=False)
        await browser.close()

    print(f"封面图已保存: {output} ({output.stat().st_size} bytes)")

asyncio.run(main())
