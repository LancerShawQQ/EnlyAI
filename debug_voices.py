"""调试音色列表"""
import os
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

from krvoiceai.app import EnlyAI
app = EnlyAI()
voices = app.list_voices()
print('total voices:', len(voices))
qwen3_count = 0
for v in voices:
    provider = v.get('provider', 'unknown')
    if provider == 'qwen3_tts':
        qwen3_count += 1
    print(f"  {v['voice_id']}: provider={provider} type={v.get('type')}")
print(f"\nQwen3-TTS voices: {qwen3_count}")
