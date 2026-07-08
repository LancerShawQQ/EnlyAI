/**
 * EnlyAI Settings Center
 * 设置中心：模型配置 / 视频设置 / 发布设置
 */

// ========== 全局状态 ==========
let _presets = null;  // provider 预设缓存
let _currentSettings = null;  // 当前完整配置（掩码后）

// ========== 工具函数 ==========

async function ensurePresets() {
  if (!_presets) {
    _presets = await api('/api/settings/presets/all');
  }
  return _presets;
}

function showTestResult(elId, result) {
  const el = document.getElementById(elId);
  if (!el) return;
  const cls = result.success ? 'success' : 'error';
  const icon = result.success ? '✓' : '✕';
  el.innerHTML = `<div class="test-result ${cls}">${icon} ${result.message}${result.elapsed_ms ? ` · ${result.elapsed_ms}ms` : ''}</div>`;
}

// ========== 子标签切换 ==========

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.sub-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.subtab;
      document.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.sub-page').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`subpage-${target}`).classList.add('active');
    });
  });
});

// ========== 加载所有设置 ==========

async function loadAllSettings() {
  try {
    await ensurePresets();
    _currentSettings = await api('/api/settings');
    loadLLMSettings();
    loadTTSSettings();
    loadASRSettings();
    loadAvatarSettings();
    updateModelStatusBadges();
  } catch (e) {
    toast(`加载设置失败: ${e.message}`, 'error');
  }
}

function updateModelStatusBadges() {
  // LLM 状态
  const llmBadge = document.getElementById('llm-status-badge');
  if (llmBadge && _currentSettings) {
    const llm = _currentSettings.llm || {};
    if (llm.provider === 'mock' || !llm.api_key_configured) {
      llmBadge.className = 'badge badge-warning';
      llmBadge.textContent = 'Mock 模式';
    } else {
      llmBadge.className = 'badge badge-success';
      llmBadge.textContent = `${llm.provider} · ${llm.model || ''}`;
    }
  }
  // TTS 状态
  const ttsBadge = document.getElementById('tts-status-badge');
  if (ttsBadge && _currentSettings) {
    const tts = _currentSettings.tts || {};
    if (tts.provider === 'mock') {
      ttsBadge.className = 'badge badge-warning';
      ttsBadge.textContent = 'Mock 模式';
    } else {
      ttsBadge.className = 'badge badge-info';
      ttsBadge.textContent = tts.provider;
    }
  }
  // Avatar 状态
  const avatarBadge = document.getElementById('avatar-status-badge');
  if (avatarBadge && _currentSettings) {
    const avatar = _currentSettings.avatar || {};
    if (avatar.provider === 'mock') {
      avatarBadge.className = 'badge badge-warning';
      avatarBadge.textContent = 'Mock 模式';
    } else {
      avatarBadge.className = 'badge badge-info';
      avatarBadge.textContent = avatar.provider;
    }
  }
}

// ========== LLM 配置 ==========

function loadLLMSettings() {
  if (!_currentSettings) return;
  const llm = _currentSettings.llm || {};
  document.getElementById('llm-provider').value = llm.provider || 'mock';
  onLLMProviderChange();
  // 模型
  const modelSelect = document.getElementById('llm-model');
  const preset = _presets.llm[llm.provider];
  if (preset && preset.models) {
    modelSelect.innerHTML = preset.models.map(m =>
      `<option value="${m}" ${m === llm.model ? 'selected' : ''}>${m}</option>`
    ).join('') + '<option value="__custom__">自定义...</option>';
    if (llm.model && !preset.models.includes(llm.model)) {
      modelSelect.value = '__custom__';
      const customInput = document.getElementById('llm-model-custom');
      customInput.style.display = 'block';
      customInput.value = llm.model;
    }
  }
  // API Key
  document.getElementById('llm-api-key').value = llm.api_key || '';
  document.getElementById('llm-key-hint').textContent = llm.api_key_configured ? '已配置' : '未配置';
  // Base URL
  document.getElementById('llm-base-url').value = llm.base_url || '';
  // 高级参数
  document.getElementById('llm-temperature').value = llm.temperature ?? 0.7;
  document.getElementById('llm-temp-val').textContent = llm.temperature ?? 0.7;
  document.getElementById('llm-max-tokens').value = llm.max_tokens || 2000;
  document.getElementById('llm-timeout').value = llm.timeout || 60;
}

function onLLMProviderChange() {
  const provider = document.getElementById('llm-provider').value;
  const preset = _presets?.llm?.[provider];
  const modelSelect = document.getElementById('llm-model');
  const customInput = document.getElementById('llm-model-custom');
  customInput.style.display = 'none';

  if (preset) {
    if (preset.models && preset.models.length) {
      modelSelect.innerHTML = preset.models.map(m => `<option value="${m}">${m}</option>`).join('') + '<option value="__custom__">自定义...</option>';
    } else {
      modelSelect.innerHTML = '<option value="">无需选择模型</option>';
    }
    // 自动填充 base_url
    if (preset.base_url) {
      document.getElementById('llm-base-url').value = preset.base_url;
    }
    // API Key 获取链接
    const urlEl = document.getElementById('llm-key-url');
    if (preset.api_key_url) {
      urlEl.innerHTML = `🔗 <a href="${preset.api_key_url}" target="_blank" style="color:var(--accent-primary)">点击获取 API Key</a>`;
    } else {
      urlEl.innerHTML = '';
    }
  }
  // model select change 处理
  modelSelect.onchange = () => {
    if (modelSelect.value === '__custom__') {
      customInput.style.display = 'block';
      customInput.focus();
    } else {
      customInput.style.display = 'none';
    }
  };
}

async function saveLLMSettings() {
  const provider = document.getElementById('llm-provider').value;
  const modelSelect = document.getElementById('llm-model');
  let model = modelSelect.value;
  if (model === '__custom__') {
    model = document.getElementById('llm-model-custom').value;
  }
  const data = {
    provider,
    model,
    api_key: document.getElementById('llm-api-key').value,
    base_url: document.getElementById('llm-base-url').value,
    temperature: parseFloat(document.getElementById('llm-temperature').value),
    max_tokens: parseInt(document.getElementById('llm-max-tokens').value),
    timeout: parseInt(document.getElementById('llm-timeout').value),
  };
  try {
    const result = await api('/api/settings/llm', {
      method: 'PUT',
      body: { section: 'llm', data },
    });
    if (result.success) {
      toast('LLM 配置已保存', 'success');
      _currentSettings = await api('/api/settings');
      updateModelStatusBadges();
    } else {
      toast(`保存失败: ${result.message}`, 'error');
    }
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetLLMSettings() {
  if (!confirm('确定重置 LLM 配置为默认？')) return;
  try {
    await api('/api/settings/llm', { method: 'DELETE' });
    toast('已重置', 'success');
    await loadAllSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

async function testLLMConnection() {
  const provider = document.getElementById('llm-provider').value;
  const modelSelect = document.getElementById('llm-model');
  let model = modelSelect.value;
  if (model === '__custom__') {
    model = document.getElementById('llm-model-custom').value;
  }
  const payload = {
    provider,
    api_key: document.getElementById('llm-api-key').value,
    base_url: document.getElementById('llm-base-url').value,
    model,
  };
  const btn = document.getElementById('llm-test-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 测试中...';
  try {
    const result = await api('/api/settings/test/llm', { method: 'POST', body: payload });
    showTestResult('llm-test-result', result);
    toast(result.success ? '连接成功' : '连接失败', result.success ? 'success' : 'error');
  } catch (e) {
    showTestResult('llm-test-result', { success: false, message: e.message });
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔌 测试连接';
  }
}

// ========== TTS 配置 ==========

function loadTTSSettings() {
  if (!_currentSettings) return;
  const tts = _currentSettings.tts || {};
  document.getElementById('tts-provider').value = tts.provider || 'mock';
  onTTSProviderChange();
  document.getElementById('tts-api-base').value = tts.api_base || '';
  document.getElementById('tts-api-key').value = tts.api_key || '';
  document.getElementById('tts-edge-voice').value = tts.edge_voice || 'zh-CN-XiaoxiaoNeural';
  document.getElementById('tts-default-voice').value = tts.default_voice || 'default';
  document.getElementById('tts-timeout').value = tts.timeout || 120;
}

function onTTSProviderChange() {
  const provider = document.getElementById('tts-provider').value;
  const edgeGroup = document.getElementById('tts-edge-voice-group');
  const apiBaseGroup = document.getElementById('tts-api-base-group');
  const apiKeyGroup = document.getElementById('tts-api-key-group');

  edgeGroup.style.display = provider === 'edge_tts' ? 'block' : 'none';
  apiBaseGroup.style.display = provider === 'gpt_sovits' ? 'block' : 'none';
  apiKeyGroup.style.display = provider === 'gpt_sovits' ? 'block' : 'none';

  // 自动填充默认地址
  if (_presets && _presets.tts[provider]) {
    const preset = _presets.tts[provider];
    if (preset.default_api_base && provider === 'gpt_sovits') {
      const cur = document.getElementById('tts-api-base').value;
      if (!cur) document.getElementById('tts-api-base').value = preset.default_api_base;
    }
  }
}

async function saveTTSSettings() {
  const data = {
    provider: document.getElementById('tts-provider').value,
    api_base: document.getElementById('tts-api-base').value,
    api_key: document.getElementById('tts-api-key').value,
    edge_voice: document.getElementById('tts-edge-voice').value,
    default_voice: document.getElementById('tts-default-voice').value,
    timeout: parseInt(document.getElementById('tts-timeout').value),
  };
  try {
    const result = await api('/api/settings/tts', {
      method: 'PUT', body: { section: 'tts', data },
    });
    if (result.success) {
      toast('TTS 配置已保存', 'success');
      _currentSettings = await api('/api/settings');
      updateModelStatusBadges();
    } else {
      toast(`保存失败: ${result.message}`, 'error');
    }
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetTTSSettings() {
  if (!confirm('确定重置 TTS 配置为默认？')) return;
  try {
    await api('/api/settings/tts', { method: 'DELETE' });
    toast('已重置', 'success');
    await loadAllSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

async function testTTSConnection() {
  const payload = {
    provider: document.getElementById('tts-provider').value,
    api_base: document.getElementById('tts-api-base').value,
    api_key: document.getElementById('tts-api-key').value,
  };
  const btn = document.getElementById('tts-test-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 测试中...';
  try {
    const result = await api('/api/settings/test/tts', { method: 'POST', body: payload });
    showTestResult('tts-test-result', result);
    toast(result.success ? '连接成功' : '连接失败', result.success ? 'success' : 'error');
  } catch (e) {
    showTestResult('tts-test-result', { success: false, message: e.message });
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔌 测试连接';
  }
}

// ========== ASR 配置 ==========

function loadASRSettings() {
  if (!_currentSettings) return;
  const asr = _currentSettings.asr || {};
  document.getElementById('asr-provider').value = asr.provider || 'mock';
  document.getElementById('asr-model').value = asr.model || 'paraformer-zh';
  document.getElementById('asr-language').value = asr.language || 'zh';
  const subtitle = asr.subtitle || {};
  document.getElementById('asr-max-chars').value = subtitle.max_chars_per_line || 18;
}

async function saveASRSettings() {
  const data = {
    provider: document.getElementById('asr-provider').value,
    model: document.getElementById('asr-model').value,
    language: document.getElementById('asr-language').value,
    subtitle: {
      max_chars_per_line: parseInt(document.getElementById('asr-max-chars').value),
    },
  };
  try {
    const result = await api('/api/settings/asr', {
      method: 'PUT', body: { section: 'asr', data },
    });
    toast(result.success ? 'ASR 配置已保存' : `保存失败: ${result.message}`,
          result.success ? 'success' : 'error');
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetASRSettings() {
  if (!confirm('确定重置 ASR 配置为默认？')) return;
  try {
    await api('/api/settings/asr', { method: 'DELETE' });
    toast('已重置', 'success');
    await loadAllSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

// ========== 数字人配置 ==========

function loadAvatarSettings() {
  if (!_currentSettings) return;
  const avatar = _currentSettings.avatar || {};
  document.getElementById('avatar-provider').value = avatar.provider || 'mock';
  onAvatarProviderChange();
  document.getElementById('avatar-default').value = avatar.default_avatar || 'default';
  document.getElementById('avatar-api-base').value = avatar.api_base || '';
  document.getElementById('avatar-fps').value = avatar.output_fps || 25;
  document.getElementById('avatar-timeout').value = avatar.timeout || 300;
  const res = avatar.output_resolution || [1080, 1920];
  document.getElementById('avatar-res-w').value = res[0];
  document.getElementById('avatar-res-h').value = res[1];
}

function onAvatarProviderChange() {
  const provider = document.getElementById('avatar-provider').value;
  const apiBaseGroup = document.getElementById('avatar-api-base-group');
  apiBaseGroup.style.display = provider === 'mock' ? 'none' : 'block';
  // 自动填充默认地址
  if (_presets && _presets.avatar[provider]) {
    const preset = _presets.avatar[provider];
    if (preset.default_api_base && provider !== 'mock') {
      const cur = document.getElementById('avatar-api-base').value;
      if (!cur) document.getElementById('avatar-api-base').value = preset.default_api_base;
    }
  }
}

function onAvatarResPresetChange(val) {
  if (!val) return;
  const [w, h] = val.split('x');
  document.getElementById('avatar-res-w').value = w;
  document.getElementById('avatar-res-h').value = h;
}

async function saveAvatarSettings() {
  const data = {
    provider: document.getElementById('avatar-provider').value,
    default_avatar: document.getElementById('avatar-default').value,
    api_base: document.getElementById('avatar-api-base').value,
    output_fps: parseInt(document.getElementById('avatar-fps').value),
    timeout: parseInt(document.getElementById('avatar-timeout').value),
    output_resolution: [
      parseInt(document.getElementById('avatar-res-w').value),
      parseInt(document.getElementById('avatar-res-h').value),
    ],
  };
  try {
    const result = await api('/api/settings/avatar', {
      method: 'PUT', body: { section: 'avatar', data },
    });
    if (result.success) {
      toast('数字人配置已保存', 'success');
      _currentSettings = await api('/api/settings');
      updateModelStatusBadges();
    } else {
      toast(`保存失败: ${result.message}`, 'error');
    }
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetAvatarSettings() {
  if (!confirm('确定重置数字人配置为默认？')) return;
  try {
    await api('/api/settings/avatar', { method: 'DELETE' });
    toast('已重置', 'success');
    await loadAllSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

async function testAvatarConnection() {
  const payload = {
    provider: document.getElementById('avatar-provider').value,
    api_base: document.getElementById('avatar-api-base').value,
  };
  const btn = document.getElementById('avatar-test-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 测试中...';
  try {
    const result = await api('/api/settings/test/avatar', { method: 'POST', body: payload });
    showTestResult('avatar-test-result', result);
    toast(result.success ? '连接成功' : '连接失败', result.success ? 'success' : 'error');
  } catch (e) {
    showTestResult('avatar-test-result', { success: false, message: e.message });
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔌 测试连接';
  }
}

// ========== 视频设置 ==========

let _videoSubStyleSelected = null;  // 视频设置页选中的字幕样式预设

async function loadVideoSettings() {
  if (!_currentSettings) {
    _currentSettings = await api('/api/settings');
  }
  const asr = _currentSettings.asr || {};
  const subtitle = asr.subtitle || {};
  const subtitleAdv = _currentSettings.subtitle || {};  // 新增字幕高级段
  const composer = _currentSettings.composer || {};
  const cover = _currentSettings.cover || {};

  // 字幕样式预设网格 + 动画下拉
  try {
    const presets = await ensureCreativePresets();
    renderSubtitleStyleGrid('video-subtitle-style-grid', presets.subtitle_styles, subtitleAdv.preset, (key) => {
      _videoSubStyleSelected = key;
      // 应用预设颜色到颜色选择器
      const style = presets.subtitle_styles[key];
      if (style) {
        document.getElementById('sub-font-color').value = assToHex(style.primary_color);
        document.getElementById('sub-outline-color').value = assToHex(style.outline_color);
        if (style.outline_width != null) document.getElementById('sub-outline-width').value = style.outline_width;
      }
    });
    _videoSubStyleSelected = subtitleAdv.preset || null;
    fillSelect('sub-animation', presets.subtitle_animations);
  } catch (e) { /* 忽略预设加载失败 */ }

  // 字幕基础（asr.subtitle）
  document.getElementById('sub-font-size').value = subtitle.font_size || 24;
  document.getElementById('sub-max-chars').value = subtitle.max_chars_per_line || 18;
  // ASS 颜色转换 &HBBGGRR -> #RRGGBB
  document.getElementById('sub-font-color').value = assToHex(subtitle.font_color || '&H00FFFFFF');
  document.getElementById('sub-outline-color').value = assToHex(subtitle.outline_color || '&H00000000');
  document.getElementById('sub-outline-width').value = subtitle.outline_width || 2;

  // 字幕高级（subtitle 段）
  if (subtitleAdv.animation) document.getElementById('sub-animation').value = subtitleAdv.animation;
  if (subtitleAdv.position) document.getElementById('sub-position').value = subtitleAdv.position;
  document.getElementById('sub-letter-spacing').value = subtitleAdv.letter_spacing || 0;
  document.getElementById('sub-dual-line').checked = !!subtitleAdv.dual_line;
  document.getElementById('sub-karaoke').checked = !!subtitleAdv.karaoke;

  // BGM
  document.getElementById('bgm-volume').value = composer.bgm_volume ?? 0.15;
  document.getElementById('bgm-vol-val').textContent = composer.bgm_volume ?? 0.15;
  document.getElementById('bgm-dir').value = composer.bgm_dir || './config/bgm';

  // 视频输出
  document.getElementById('video-fps').value = composer.output_fps || 30;
  document.getElementById('video-bitrate').value = composer.video_bitrate || '8M';
  document.getElementById('audio-bitrate').value = composer.audio_bitrate || '192k';
  const res = composer.output_resolution || [1080, 1920];
  document.getElementById('video-ratio').value = `${res[0]}x${res[1]}`;
  document.getElementById('ffmpeg-path').value = composer.ffmpeg_path || 'ffmpeg';

  // 封面
  document.getElementById('cover-mode').value = cover.mode || 'frame_overlay';
  document.getElementById('cover-max-chars').value = cover.title_max_chars || 20;
  document.getElementById('cover-font-path').value = cover.font_path || './config/fonts/SourceHanSansCN-Bold.otf';
  // 封面样式选择与预览
  _coverSelectedStyle = cover.style_id || 'deep_blue';
  if (typeof loadCoverStyles === 'function') loadCoverStyles();
  const coverTitleInput = document.getElementById('cover-preview-title');
  if (coverTitleInput) {
    coverTitleInput.addEventListener('input', () => {
      clearTimeout(_coverPreviewTimer);
      _coverPreviewTimer = setTimeout(generateCoverPreview, 600);
    });
  }
  const coverRegenBtn = document.getElementById('cover-regenerate-btn');
  if (coverRegenBtn) coverRegenBtn.addEventListener('click', generateCoverPreview);
}

function onVideoRatioChange(val) {
  if (!val) return;
  // 仅用于显示提示，实际分辨率在保存时写入
}

async function saveVideoSettings() {
  // 字幕颜色转回 ASS 格式 #RRGGBB -> &HBBGGRR
  const fontColor = hexToAss(document.getElementById('sub-font-color').value);
  const outlineColor = hexToAss(document.getElementById('sub-outline-color').value);
  const maxChars = parseInt(document.getElementById('sub-max-chars').value);

  // ASR 段（字幕基础样式）
  const asrData = {
    subtitle: {
      font_size: parseInt(document.getElementById('sub-font-size').value),
      font_color: fontColor,
      outline_color: outlineColor,
      outline_width: parseFloat(document.getElementById('sub-outline-width').value),
      max_chars_per_line: maxChars,
    },
  };
  // 字幕高级段（subtitle）
  const subtitleData = {
    preset: _videoSubStyleSelected || 'minimal_white',
    animation: document.getElementById('sub-animation').value,
    position: document.getElementById('sub-position').value,
    font_size: parseInt(document.getElementById('sub-font-size').value),
    primary_color: fontColor,
    outline_color: outlineColor,
    outline_width: parseFloat(document.getElementById('sub-outline-width').value),
    letter_spacing: parseInt(document.getElementById('sub-letter-spacing').value),
    dual_line: document.getElementById('sub-dual-line').checked,
    karaoke: document.getElementById('sub-karaoke').checked,
  };
  // Composer 段
  const ratio = document.getElementById('video-ratio').value.split('x');
  const composerData = {
    ffmpeg_path: document.getElementById('ffmpeg-path').value,
    output_fps: parseInt(document.getElementById('video-fps').value),
    output_resolution: [parseInt(ratio[0]), parseInt(ratio[1])],
    video_bitrate: document.getElementById('video-bitrate').value,
    audio_bitrate: document.getElementById('audio-bitrate').value,
    bgm_dir: document.getElementById('bgm-dir').value,
    bgm_volume: parseFloat(document.getElementById('bgm-volume').value),
  };
  // Cover 段
  const coverData = {
    mode: document.getElementById('cover-mode').value,
    style_id: _coverSelectedStyle || 'deep_blue',
    title_max_chars: parseInt(document.getElementById('cover-max-chars').value),
    font_path: document.getElementById('cover-font-path').value,
  };

  try {
    await api('/api/settings/asr', { method: 'PUT', body: { section: 'asr', data: asrData } });
    await api('/api/settings/subtitle', { method: 'PUT', body: { section: 'subtitle', data: subtitleData } });
    await api('/api/settings/composer', { method: 'PUT', body: { section: 'composer', data: composerData } });
    await api('/api/settings/cover', { method: 'PUT', body: { section: 'cover', data: coverData } });
    toast('视频设置已保存', 'success');
    _currentSettings = await api('/api/settings');
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetVideoSettings() {
  if (!confirm('确定重置视频设置为默认？')) return;
  try {
    await api('/api/settings/asr', { method: 'DELETE' });
    await api('/api/settings/subtitle', { method: 'DELETE' });
    await api('/api/settings/composer', { method: 'DELETE' });
    await api('/api/settings/cover', { method: 'DELETE' });
    toast('已重置', 'success');
    _currentSettings = await api('/api/settings');
    loadVideoSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

// ========== 场景与效果设置 ==========

async function loadSceneEffectSettings() {
  if (!_currentSettings) {
    _currentSettings = await api('/api/settings');
  }
  const scene = _currentSettings.scene || {};
  const audio = _currentSettings.audio || {};
  const effects = _currentSettings.effects || {};

  let presets;
  try { presets = await ensureCreativePresets(); } catch (e) { presets = null; }

  // 数字人场景
  if (presets) {
    renderBtnCardGrid('scene-pose-grid', presets.poses, POSE_ICONS);
    // 非 half_body 姿态标注“即将支持”（当前仅 half_body 可用）
    document.querySelectorAll('#scene-pose-grid .btn-card').forEach(btn => {
      if (btn.dataset.value !== 'half_body') {
        btn.disabled = true;
        btn.title = '即将支持';
        const label = btn.querySelector('.btn-card-label');
        if (label && !label.textContent.includes('即将支持')) {
          label.textContent = label.textContent + ' (即将支持)';
        }
      }
    });
    fillSelect('effect-transition', presets.transitions);
    fillSelect('effect-filter', presets.filters);
    renderBtnCardGrid('audio-emotion-grid', presets.emotions, EMOTION_ICONS);
  }
  setBtnCardValue('scene-pose-grid', scene.pose || 'half_body');
  setBtnCardValue('scene-position-grid', scene.position || 'center');
  setBtnCardValue('scene-bg-type-grid', scene.background_type || 'transparent');
  setBtnCardValue('audio-emotion-grid', audio.emotion || 'neutral');
  bindBtnCardGrid('scene-pose-grid');
  bindBtnCardGrid('scene-position-grid');
  bindBtnCardGrid('scene-bg-type-grid', (val) => {
    document.getElementById('scene-bg-color-group').style.display = val === 'solid' ? 'block' : 'none';
    document.getElementById('scene-bg-image-group').style.display = val === 'image' ? 'block' : 'none';
  });
  bindBtnCardGrid('audio-emotion-grid');

  // 场景数值
  document.getElementById('scene-scale').value = scene.scale ?? 1.0;
  document.getElementById('scene-scale-val').textContent = scene.scale ?? 1.0;
  document.getElementById('scene-bg-color').value = scene.background_color || '#1a1a2e';
  document.getElementById('scene-bg-image').value = scene.background_image || '';
  document.getElementById('scene-show-logo').checked = !!scene.show_logo;
  document.getElementById('scene-logo-position').value = scene.logo_position || 'bottom-right';
  const logoImgInput = document.getElementById('settings-logo-image');
  if (logoImgInput) logoImgInput.value = scene.logo_image || '';
  document.getElementById('scene-logo-position-group').style.display = scene.show_logo ? 'block' : 'none';
  const logoImgGroup = document.getElementById('settings-logo-image-group');
  if (logoImgGroup) logoImgGroup.style.display = scene.show_logo ? 'block' : 'none';
  document.getElementById('scene-bg-color-group').style.display = (scene.background_type === 'solid') ? 'block' : 'none';
  document.getElementById('scene-bg-image-group').style.display = (scene.background_type === 'image') ? 'block' : 'none';

  // 音频效果
  document.getElementById('audio-speed').value = audio.speed ?? 1.0;
  document.getElementById('audio-speed-val').textContent = audio.speed ?? 1.0;
  document.getElementById('audio-volume').value = audio.volume ?? 100;
  document.getElementById('audio-volume-val').textContent = audio.volume ?? 100;
  document.getElementById('audio-pitch').value = audio.pitch ?? 0;
  document.getElementById('audio-pitch-val').textContent = audio.pitch ?? 0;
  document.getElementById('audio-pause').value = audio.pause_duration ?? 0.5;
  document.getElementById('audio-pause-val').textContent = (audio.pause_duration ?? 0.5) + 's';
  document.getElementById('audio-remove-silence').checked = !!audio.remove_silence;
  document.getElementById('audio-voice-enhance').checked = !!audio.voice_enhance;

  // 视频效果
  if (effects.transition && presets) document.getElementById('effect-transition').value = effects.transition;
  if (effects.filter && presets) document.getElementById('effect-filter').value = effects.filter;
  document.getElementById('effect-transition-dur').value = effects.transition_duration ?? 0.5;
  document.getElementById('effect-transition-dur-val').textContent = (effects.transition_duration ?? 0.5) + 's';
  document.getElementById('effect-filter-intensity').value = effects.filter_intensity ?? 50;
  document.getElementById('effect-filter-intensity-val').textContent = effects.filter_intensity ?? 50;

  // 水印
  const watermark = effects.watermark || {};
  document.getElementById('effect-watermark-enabled').checked = !!watermark.enabled;
  document.getElementById('effect-watermark-text').value = watermark.text || '';
  document.getElementById('effect-watermark-position').value = watermark.position || 'bottom-right';
  document.getElementById('effect-watermark-opacity').value = watermark.opacity ?? 50;
  document.getElementById('effect-watermark-opacity-val').textContent = watermark.opacity ?? 50;
  document.getElementById('effect-watermark-group').style.display = watermark.enabled ? 'block' : 'none';

  // 片头片尾
  const intro = effects.intro || {};
  const outro = effects.outro || {};
  document.getElementById('effect-intro-enabled').checked = !!intro.enabled;
  document.getElementById('effect-intro-text').value = intro.text || '';
  document.getElementById('effect-intro-duration').value = intro.duration || 3;
  document.getElementById('effect-outro-enabled').checked = !!outro.enabled;
  document.getElementById('effect-outro-text').value = outro.text || '';
  document.getElementById('effect-outro-duration').value = outro.duration || 3;

  // 开关联动
  const logoCheck = document.getElementById('scene-show-logo');
  if (!logoCheck._bound) {
    logoCheck._bound = true;
    logoCheck.addEventListener('change', e => {
      document.getElementById('scene-logo-position-group').style.display = e.target.checked ? 'block' : 'none';
      const lig = document.getElementById('settings-logo-image-group');
      if (lig) lig.style.display = e.target.checked ? 'block' : 'none';
    });
    document.getElementById('effect-watermark-enabled').addEventListener('change', e => {
      document.getElementById('effect-watermark-group').style.display = e.target.checked ? 'block' : 'none';
    });
  }
}

async function saveSceneEffectSettings() {
  const sceneData = {
    pose: getBtnCardValue('scene-pose-grid') || 'half_body',
    position: getBtnCardValue('scene-position-grid') || 'center',
    scale: parseFloat(document.getElementById('scene-scale').value),
    background_type: getBtnCardValue('scene-bg-type-grid') || 'transparent',
    background_color: document.getElementById('scene-bg-color').value,
    background_image: document.getElementById('scene-bg-image').value,
    show_logo: document.getElementById('scene-show-logo').checked,
    logo_position: document.getElementById('scene-logo-position').value,
    logo_image: document.getElementById('settings-logo-image')?.value || '',
  };
  const audioData = {
    speed: parseFloat(document.getElementById('audio-speed').value),
    volume: parseInt(document.getElementById('audio-volume').value),
    pitch: parseInt(document.getElementById('audio-pitch').value),
    emotion: getBtnCardValue('audio-emotion-grid') || 'neutral',
    pause_duration: parseFloat(document.getElementById('audio-pause').value),
    remove_silence: document.getElementById('audio-remove-silence').checked,
    voice_enhance: document.getElementById('audio-voice-enhance').checked,
  };
  const effectsData = {
    transition: document.getElementById('effect-transition').value,
    transition_duration: parseFloat(document.getElementById('effect-transition-dur').value),
    filter: document.getElementById('effect-filter').value,
    filter_intensity: parseInt(document.getElementById('effect-filter-intensity').value),
    watermark: {
      enabled: document.getElementById('effect-watermark-enabled').checked,
      text: document.getElementById('effect-watermark-text').value,
      position: document.getElementById('effect-watermark-position').value,
      opacity: parseInt(document.getElementById('effect-watermark-opacity').value),
    },
    intro: {
      enabled: document.getElementById('effect-intro-enabled').checked,
      text: document.getElementById('effect-intro-text').value,
      duration: parseInt(document.getElementById('effect-intro-duration').value) || 3,
    },
    outro: {
      enabled: document.getElementById('effect-outro-enabled').checked,
      text: document.getElementById('effect-outro-text').value,
      duration: parseInt(document.getElementById('effect-outro-duration').value) || 3,
    },
  };
  try {
    await api('/api/settings/scene', { method: 'PUT', body: { section: 'scene', data: sceneData } });
    await api('/api/settings/audio', { method: 'PUT', body: { section: 'audio', data: audioData } });
    await api('/api/settings/effects', { method: 'PUT', body: { section: 'effects', data: effectsData } });
    toast('场景与效果设置已保存', 'success');
    _currentSettings = await api('/api/settings');
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetSceneEffectSettings() {
  if (!confirm('确定重置场景与效果设置为默认？')) return;
  try {
    await api('/api/settings/scene', { method: 'DELETE' });
    await api('/api/settings/audio', { method: 'DELETE' });
    await api('/api/settings/effects', { method: 'DELETE' });
    toast('已重置', 'success');
    _currentSettings = await api('/api/settings');
    loadSceneEffectSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

// ========== 发布设置 ==========

const PLATFORM_INFO = {
  bilibili: { name: '哔哩哔哩', icon: '📺', method: 'api' },
  douyin: { name: '抖音', icon: '🎵', method: 'playwright' },
  kuaishou: { name: '快手', icon: '⚡', method: 'playwright' },
  wechat_video: { name: '微信视频号', icon: '💬', method: 'playwright' },
};

async function loadPublishSettings() {
  if (!_currentSettings) {
    _currentSettings = await api('/api/settings');
  }
  const pub = _currentSettings.publisher || {};
  document.getElementById('pub-mode').value = pub.mode || 'semi_auto';
  document.getElementById('pub-interval').value = pub.publish_interval || 60;

  // 渲染平台卡片
  const listEl = document.getElementById('platform-list');
  const platforms = pub.platforms || {};
  listEl.innerHTML = Object.entries(PLATFORM_INFO).map(([key, info]) => {
    const conf = platforms[key] || {};
    const enabled = conf.enabled !== false;
    return `
      <div class="platform-card" data-platform="${key}">
        <div class="platform-card-header">
          <div class="platform-name">
            <span class="platform-icon">${info.icon}</span>
            <span>${info.name}</span>
          </div>
          <div class="platform-toggle ${enabled ? 'active' : ''}" onclick="togglePlatform('${key}', this)"></div>
        </div>
        <div class="platform-meta">
          <div class="platform-meta-row">
            <span>发布方式</span>
            <span>${conf.method || info.method}</span>
          </div>
          <div class="platform-meta-row">
            <span>API 地址</span>
            <span>${conf.api_base || '默认'}</span>
          </div>
          <div class="platform-meta-row">
            <span>登录状态</span>
            <span class="badge ${enabled ? 'badge-success' : 'badge-muted'}">${enabled ? '已启用' : '未启用'}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');

  // 初始化 Cookie 管理 + 一键分发
  loadCookieManager();
  loadPublishJobSelect();
  loadPublishPlatformsGrid();
  const publishRunBtn = document.getElementById('publish-run-btn');
  if (publishRunBtn) publishRunBtn.addEventListener('click', runPublishVideo);
}

function togglePlatform(key, el) {
  el.classList.toggle('active');
}

// ========== Cookie 管理 + 一键分发（对标蝉妈妈/新榜矩阵分发） ==========

async function loadCookieManager() {
  const listEl = document.getElementById('cookie-manager-list');
  if (!listEl) return;
  try {
    const result = await api('/api/publish/cookies');
    const cookies = result.cookies || {};
    listEl.innerHTML = Object.entries(PLATFORM_INFO).map(([key, info]) => {
      const c = cookies[key] || {};
      const configured = c.configured;
      const enabled = c.enabled;
      // B站支持扫码登录，其他平台用浏览器自动登录
      const loginBtn = key === 'bilibili'
        ? `<button class="btn btn-sm btn-primary" onclick="loginBilibiliQrcode()" id="bilibili-login-btn">扫码登录</button>`
        : `<button class="btn btn-sm btn-primary" onclick="loginBrowserPlatform('${key}')">浏览器登录</button>`;
      return `
        <div class="cookie-mgr-card" data-platform="${key}" style="padding:12px;border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--bg-elevated)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div style="display:flex;gap:8px;align-items:center">
              <span style="font-size:20px">${info.icon}</span>
              <span style="font-weight:600">${info.name}</span>
              <span class="badge ${configured ? 'badge-success' : 'badge-muted'}">${configured ? '已配置' : '未配置'}</span>
              ${enabled ? '<span class="badge badge-info">已启用</span>' : ''}
            </div>
            <div style="display:flex;gap:6px">
              ${loginBtn}
              ${configured ? `<button class="btn btn-sm btn-secondary" onclick="deleteCookie('${key}')">删除</button>` : ''}
            </div>
          </div>
          <div style="font-size:11px;color:var(--color-text-secondary);margin-bottom:6px">
            ${key === 'bilibili' ? '推荐扫码登录，自动获取Cookie' : '推荐浏览器登录，自动获取Cookie'}
          </div>
          <details style="margin-top:4px">
            <summary style="font-size:11px;color:var(--color-text-secondary);cursor:pointer">手动输入 Cookie（高级）</summary>
            <textarea class="form-textarea" id="cookie-input-${key}" style="min-height:50px;font-size:11px;margin-top:6px" placeholder='粘贴 ${info.name} 的 Cookie（JSON 格式或 raw 字符串）'></textarea>
            <button class="btn btn-sm btn-secondary" style="margin-top:6px" onclick="saveCookie('${key}')">保存 Cookie</button>
          </details>
          <div id="bilibili-qrcode-area" style="text-align:center;margin-top:8px"></div>
        </div>
      `;
    }).join('');
  } catch (e) {
    listEl.innerHTML = `<div class="hint">加载 Cookie 状态失败: ${e.message}</div>`;
  }
}

// B站扫码登录
let _bilibiliLoginPolling = false;
async function loginBilibiliQrcode() {
  const btn = document.getElementById('bilibili-login-btn');
  const qrcodeArea = document.getElementById('bilibili-qrcode-area');
  if (!btn) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 获取二维码...';
  if (qrcodeArea) qrcodeArea.innerHTML = '';
  try {
    const result = await api('/api/publish/login/bilibili/qrcode', { method: 'POST' });
    if (!result.qrcode_url && !result.qrcode_image) throw new Error('未获取到二维码');
    // 显示二维码
    if (result.qrcode_image) {
      // base64 图片
      if (qrcodeArea) qrcodeArea.innerHTML = `
        <div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">请用哔哩哔哩APP扫描二维码登录</div>
        <img src="data:image/png;base64,${result.qrcode_image}" style="max-width:200px;border:1px solid var(--border-default);border-radius:8px" />
        <div style="font-size:11px;color:var(--color-text-secondary);margin-top:4px">等待扫码确认...</div>
      `;
    } else if (result.qrcode_url) {
      if (qrcodeArea) qrcodeArea.innerHTML = `
        <div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">请用哔哩哔哩APP扫描二维码登录</div>
        <img src="${result.qrcode_url}" style="max-width:200px;border:1px solid var(--border-default);border-radius:8px" />
        <div style="font-size:11px;color:var(--color-text-secondary);margin-top:4px">等待扫码确认...</div>
      `;
    }
    btn.innerHTML = '等待扫码...';
    // 轮询检查扫码状态
    _bilibiliLoginPolling = true;
    _pollBilibiliLogin();
  } catch (e) {
    toast(`B站扫码登录失败: ${e.message}`, 'error');
    btn.disabled = false;
    btn.innerHTML = '扫码登录';
  }
}

async function _pollBilibiliLogin() {
  if (!_bilibiliLoginPolling) return;
  try {
    const result = await api('/api/publish/login/bilibili/check');
    if (result.status === 'success' || result.success) {
      _bilibiliLoginPolling = false;
      const btn = document.getElementById('bilibili-login-btn');
      const qrcodeArea = document.getElementById('bilibili-qrcode-area');
      if (btn) { btn.disabled = false; btn.innerHTML = '扫码登录'; }
      if (qrcodeArea) qrcodeArea.innerHTML = '<div style="color:var(--color-success);font-size:13px;padding:8px">✓ 登录成功，Cookie已自动保存</div>';
      toast('B站登录成功！Cookie已自动保存', 'success');
      loadCookieManager();
      return;
    }
    if (result.status === 'expired' || result.status === 'failed') {
      _bilibiliLoginPolling = false;
      const btn = document.getElementById('bilibili-login-btn');
      const qrcodeArea = document.getElementById('bilibili-qrcode-area');
      if (btn) { btn.disabled = false; btn.innerHTML = '扫码登录'; }
      if (qrcodeArea) qrcodeArea.innerHTML = '<div style="color:var(--color-error);font-size:13px;padding:8px">二维码已过期，请重新扫码</div>';
      toast('二维码已过期，请重新扫码', 'error');
      return;
    }
    // 继续轮询（每2秒）
    setTimeout(_pollBilibiliLogin, 2000);
  } catch (e) {
    _bilibiliLoginPolling = false;
    const btn = document.getElementById('bilibili-login-btn');
    if (btn) { btn.disabled = false; btn.innerHTML = '扫码登录'; }
    toast(`检查扫码状态失败: ${e.message}`, 'error');
  }
}

// 浏览器自动登录（抖音/快手/视频号）
async function loginBrowserPlatform(platform) {
  const platformName = PLATFORM_INFO[platform]?.name || platform;
  toast(`正在打开浏览器登录${platformName}，请在弹出窗口中完成登录...`, 'info');
  try {
    const result = await api(`/api/publish/login/${platform}`, { method: 'POST' });
    if (result.success || result.status === 'success') {
      toast(`${platformName}登录成功！Cookie已自动保存`, 'success');
      loadCookieManager();
    } else {
      toast(`${platformName}登录未完成: ${result.message || result.error || '可能超时或用户取消'}`, 'error');
    }
  } catch (e) {
    toast(`${platformName}浏览器登录失败: ${e.message}`, 'error');
  }
}

async function saveCookie(platform) {
  const input = document.getElementById(`cookie-input-${platform}`);
  if (!input || !input.value.trim()) {
    toast('请输入 Cookie', 'error');
    return;
  }
  const val = input.value.trim();
  let body;
  // 尝试解析为 JSON，失败则当作 raw 字符串
  try {
    const parsed = JSON.parse(val);
    body = { cookie: parsed };
  } catch {
    body = { cookie_text: val };
  }
  try {
    await api(`/api/publish/cookies/${platform}`, { method: 'POST', body });
    toast(`${PLATFORM_INFO[platform].name} Cookie 已保存`, 'success');
    input.value = '';
    loadCookieManager();
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function deleteCookie(platform) {
  if (!confirm(`确定删除 ${PLATFORM_INFO[platform].name} 的 Cookie？`)) return;
  try {
    await api(`/api/publish/cookies/${platform}`, { method: 'DELETE' });
    toast('Cookie 已删除', 'success');
    loadCookieManager();
  } catch (e) {
    toast(`删除失败: ${e.message}`, 'error');
  }
}

async function loadPublishJobSelect() {
  const sel = document.getElementById('publish-job-select');
  if (!sel) return;
  try {
    const jobs = await api('/api/jobs?limit=20');
    const jobList = jobs.jobs || jobs || [];
    const completed = jobList.filter(j => j.video_path && j.status === 'success');
    sel.innerHTML = '<option value="">-- 选择已完成的任务 --</option>' +
      completed.map(j => `<option value="${j.job_id}">${j.job_id} · ${j.title || j.video_path.split(/[\\/]/).pop() || ''}</option>`).join('');
  } catch (e) {
    sel.innerHTML = `<option value="">加载失败: ${e.message}</option>`;
  }
}

function loadPublishPlatformsGrid() {
  const grid = document.getElementById('publish-platforms-grid');
  if (!grid) return;
  grid.innerHTML = Object.entries(PLATFORM_INFO).map(([key, info]) => `
    <label class="matrix-checkbox-item">
      <input type="checkbox" value="${key}">
      <span>${info.icon} ${info.name}</span>
    </label>
  `).join('');
}

async function runPublishVideo() {
  const jobId = document.getElementById('publish-job-select').value;
  const platforms = Array.from(document.querySelectorAll('#publish-platforms-grid input:checked')).map(c => c.value);
  const title = document.getElementById('publish-title').value.trim();
  const description = document.getElementById('publish-description').value.trim();
  const tagsText = document.getElementById('publish-tags').value.trim();
  const resultEl = document.getElementById('publish-result');
  const btn = document.getElementById('publish-run-btn');

  if (!jobId) { toast('请选择任务', 'error'); return; }
  if (!platforms.length) { toast('请选择分发平台', 'error'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 分发中...';
  resultEl.innerHTML = '<div style="color:#666;font-size:13px;padding:8px">正在分发到 ' + platforms.length + ' 个平台...</div>';

  try {
    const tags = tagsText ? tagsText.split(/[,，]/).map(t => t.trim()).filter(t => t) : [];
    const result = await api('/api/publish', {
      method: 'POST',
      body: { job_id: jobId, platforms, title, description, tags },
    });
    if (result.success) {
      const results = result.results || [];
      const successCount = result.success_count || 0;
      const totalCount = result.total_count || results.length;
      resultEl.innerHTML = `
        <div style="padding:10px;background:#e8f5e9;border:1px solid #81c784;border-radius:6px;margin-bottom:8px">
          <strong>分发完成：${successCount}/${totalCount} 平台成功</strong>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px">
          ${results.map(r => {
            const info = PLATFORM_INFO[r.platform] || { name: r.platform, icon: '' };
            const ok = r.status === 'success';
            const color = ok ? '#2e7d32' : (r.status === 'skipped' ? '#f57c00' : '#c62828');
            const bg = ok ? '#e8f5e9' : (r.status === 'skipped' ? '#fff3e0' : '#ffebee');
            return `
              <div style="padding:8px;background:${bg};border-radius:4px;font-size:12px">
                <div style="display:flex;justify-content:space-between">
                  <span>${info.icon} ${info.name}</span>
                  <span style="color:${color};font-weight:600">${r.status}</span>
                </div>
                ${r.url ? `<div style="color:#666;margin-top:4px"><a href="${r.url}" target="_blank">${r.url}</a></div>` : ''}
                ${r.error ? `<div style="color:#c62828;margin-top:4px">${escapeHtml(r.error)}</div>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      `;
      toast(`分发完成：${successCount}/${totalCount} 成功`, successCount === totalCount ? 'success' : 'info');
    } else {
      resultEl.innerHTML = `<div style="padding:10px;background:#ffebee;border:1px solid #ef9a9a;border-radius:6px;color:#c62828">分发失败：${escapeHtml(result.error || '未知错误')}</div>`;
      toast('分发失败', 'error');
    }
  } catch (e) {
    resultEl.innerHTML = `<div style="padding:10px;background:#ffebee;border:1px solid #ef9a9a;border-radius:6px;color:#c62828">请求失败：${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="send"></i> 一键分发';
    if (window.lucide) lucide.createIcons();
  }
}

async function savePublishSettings() {
  const mode = document.getElementById('pub-mode').value;
  const interval = parseInt(document.getElementById('pub-interval').value);

  // 收集平台启用状态
  const platforms = {};
  document.querySelectorAll('.platform-card').forEach(card => {
    const key = card.dataset.platform;
    const toggle = card.querySelector('.platform-toggle');
    platforms[key] = {
      enabled: toggle.classList.contains('active'),
      method: PLATFORM_INFO[key].method,
    };
    if (key === 'bilibili') {
      platforms[key].api_base = 'https://api.bilibili.com';
    }
  });

  const data = {
    mode,
    publish_interval: interval,
    platforms,
  };
  try {
    const result = await api('/api/settings/publisher', {
      method: 'PUT', body: { section: 'publisher', data },
    });
    toast(result.success ? '发布设置已保存' : `保存失败: ${result.message}`,
          result.success ? 'success' : 'error');
    if (result.success) {
      _currentSettings = await api('/api/settings');
      loadPublishSettings();
    }
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function resetPublishSettings() {
  if (!confirm('确定重置发布设置为默认？')) return;
  try {
    await api('/api/settings/publisher', { method: 'DELETE' });
    toast('已重置', 'success');
    _currentSettings = await api('/api/settings');
    loadPublishSettings();
  } catch (e) {
    toast(`重置失败: ${e.message}`, 'error');
  }
}

// ========== 绑定设置按钮 ==========

document.addEventListener('DOMContentLoaded', () => {
  // LLM
  document.getElementById('llm-save-btn')?.addEventListener('click', saveLLMSettings);
  document.getElementById('llm-reset-btn')?.addEventListener('click', resetLLMSettings);
  document.getElementById('llm-test-btn')?.addEventListener('click', testLLMConnection);
  document.getElementById('llm-toggle-key')?.addEventListener('click', () => {
    const input = document.getElementById('llm-api-key');
    input.type = input.type === 'password' ? 'text' : 'password';
  });
  // TTS
  document.getElementById('tts-save-btn')?.addEventListener('click', saveTTSSettings);
  document.getElementById('tts-reset-btn')?.addEventListener('click', resetTTSSettings);
  document.getElementById('tts-test-btn')?.addEventListener('click', testTTSConnection);
  // ASR
  document.getElementById('asr-save-btn')?.addEventListener('click', saveASRSettings);
  document.getElementById('asr-reset-btn')?.addEventListener('click', resetASRSettings);
  // Avatar
  document.getElementById('avatar-save-btn')?.addEventListener('click', saveAvatarSettings);
  document.getElementById('avatar-reset-btn')?.addEventListener('click', resetAvatarSettings);
  document.getElementById('avatar-test-btn')?.addEventListener('click', testAvatarConnection);
  // Video
  document.getElementById('video-save-btn')?.addEventListener('click', saveVideoSettings);
  document.getElementById('video-reset-btn')?.addEventListener('click', resetVideoSettings);
  // Scene & Effects
  document.getElementById('scene-save-btn')?.addEventListener('click', saveSceneEffectSettings);
  document.getElementById('scene-reset-btn')?.addEventListener('click', resetSceneEffectSettings);
  // Publish
  document.getElementById('publish-save-btn')?.addEventListener('click', savePublishSettings);
  document.getElementById('publish-reset-btn')?.addEventListener('click', resetPublishSettings);
});
