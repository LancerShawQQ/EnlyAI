/**
 * EnlyAI Settings Center
 * 设置中心：模型配置 / 视频设置 / 发布设置
 */

// ========== 全局状态 ==========
let _presets = null;  // provider 预设缓存
let _currentSettings = null;  // 当前完整配置（掩码后）
let _platformLoginStatus = {};  // 平台登录态校验结果缓存 {platform: {logged_in, ...}}

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
      // 联动 P1：广播设置变更事件，通知向导实时刷新
      window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'llm' } }));
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
  document.getElementById('tts-provider').value = tts.provider || 'moss_nano';
  onTTSProviderChange();
  document.getElementById('tts-api-base').value = tts.api_base || '';
  document.getElementById('tts-api-key').value = tts.api_key || '';
  document.getElementById('tts-edge-voice').value = tts.edge_voice || 'zh-CN-XiaoxiaoNeural';
  // MOSS NANO 内置音色回填
  const mossVoice = (tts.moss_nano && tts.moss_nano.builtin_voice) || tts.default_voice || 'Junhao';
  const mossSel = document.getElementById('tts-moss-voice');
  if (mossSel) mossSel.value = mossVoice;
  document.getElementById('tts-default-voice').value = tts.default_voice || 'Junhao';
  document.getElementById('tts-timeout').value = tts.timeout || 120;
}

function onTTSProviderChange() {
  const provider = document.getElementById('tts-provider').value;
  const edgeGroup = document.getElementById('tts-edge-voice-group');
  const mossGroup = document.getElementById('tts-moss-voice-group');
  const apiBaseGroup = document.getElementById('tts-api-base-group');
  const apiKeyGroup = document.getElementById('tts-api-key-group');
  const defaultVoiceInput = document.getElementById('tts-default-voice');

  edgeGroup.style.display = provider === 'edge_tts' ? 'block' : 'none';
  mossGroup.style.display = provider === 'moss_nano' ? 'block' : 'none';
  apiBaseGroup.style.display = (provider === 'gpt_sovits' || provider === 'mimo') ? 'block' : 'none';
  apiKeyGroup.style.display = (provider === 'gpt_sovits' || provider === 'mimo') ? 'block' : 'none';

  // 根据 provider 自动同步 default_voice
  if (provider === 'edge_tts') {
    defaultVoiceInput.value = document.getElementById('tts-edge-voice').value;
  } else if (provider === 'moss_nano') {
    defaultVoiceInput.value = document.getElementById('tts-moss-voice').value;
  }

  // 音色下拉变化时同步 default_voice
  document.getElementById('tts-edge-voice').onchange = () => {
    if (document.getElementById('tts-provider').value === 'edge_tts') defaultVoiceInput.value = document.getElementById('tts-edge-voice').value;
  };
  document.getElementById('tts-moss-voice').onchange = () => {
    if (document.getElementById('tts-provider').value === 'moss_nano') defaultVoiceInput.value = document.getElementById('tts-moss-voice').value;
  };

  // 自动填充默认地址
  if (_presets && _presets.tts[provider]) {
    const preset = _presets.tts[provider];
    if (preset.default_api_base && (provider === 'gpt_sovits' || provider === 'mimo')) {
      const cur = document.getElementById('tts-api-base').value;
      if (!cur) document.getElementById('tts-api-base').value = preset.default_api_base;
    }
  }
}

async function saveTTSSettings() {
  const provider = document.getElementById('tts-provider').value;
  // 根据 provider 确定 default_voice
  let defaultVoice = document.getElementById('tts-default-voice').value;
  if (provider === 'edge_tts') {
    defaultVoice = document.getElementById('tts-edge-voice').value;
  } else if (provider === 'moss_nano') {
    defaultVoice = document.getElementById('tts-moss-voice').value;
  }
  const data = {
    provider: provider,
    api_base: document.getElementById('tts-api-base').value,
    api_key: document.getElementById('tts-api-key').value,
    edge_voice: document.getElementById('tts-edge-voice').value,
    default_voice: defaultVoice,
    timeout: parseInt(document.getElementById('tts-timeout').value),
  };
  // MOSS NANO 额外保存 builtin_voice
  if (provider === 'moss_nano') {
    data.moss_nano = { builtin_voice: document.getElementById('tts-moss-voice').value };
  }
  try {
    const result = await api('/api/settings/tts', {
      method: 'PUT', body: { section: 'tts', data },
    });
    if (result.success) {
      toast('TTS 配置已保存', 'success');
      _currentSettings = await api('/api/settings');
      updateModelStatusBadges();
      // provider 切换后使向导音色库缓存失效，下次进入向导时重新拉取对应音色
      if (typeof window !== 'undefined') {
        window._wizardVoiceList = null;
        window._wizardVoiceProvider = data.provider;
      }
      // 联动 P1：广播设置变更事件，通知向导实时刷新音色列表
      window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'tts' } }));
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
    // 联动 P1：广播设置变更事件，通知向导实时刷新字幕样式
    if (result.success) {
      window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'asr' } }));
    }
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
  // LongCat 配置回填
  const longcat = avatar.longcat || {};
  document.getElementById('longcat-server-url').value = longcat.server_url || '';
  document.getElementById('longcat-api-key').value = longcat.api_key || '';
  document.getElementById('longcat-model-type').value = longcat.model_type || 'avatar-v1.5';
  document.getElementById('longcat-resolution').value = longcat.resolution || '480p';
  document.getElementById('longcat-timeout').value = longcat.timeout || 600;
  // MuseTalk 配置回填
  const musetalk = avatar.musetalk || {};
  document.getElementById('musetalk-server-url').value = musetalk.server_url || '';
  document.getElementById('musetalk-api-key').value = musetalk.api_key || '';
  document.getElementById('musetalk-version').value = musetalk.version || 'v15';
  document.getElementById('musetalk-use-float16').value = String(musetalk.use_float16 !== false);
  document.getElementById('musetalk-fps').value = musetalk.fps || 25;
  document.getElementById('musetalk-bbox-shift').value = musetalk.bbox_shift || 5;
}

function onAvatarProviderChange() {
  const provider = document.getElementById('avatar-provider').value;
  const apiBaseGroup = document.getElementById('avatar-api-base-group');
  const longcatGroup = document.getElementById('avatar-longcat-group');
  const musetalkGroup = document.getElementById('avatar-musetalk-group');
  // api-base 仅对 latentsync/echomimic 显示（musetalk/longcat 有独立配置区）
  const showApiBase = ['latentsync', 'echomimic'].includes(provider);
  apiBaseGroup.style.display = showApiBase ? 'block' : 'none';
  // LongCat 配置区仅对 longcat 显示
  longcatGroup.style.display = provider === 'longcat' ? 'block' : 'none';
  // MuseTalk 配置区仅对 musetalk 显示
  musetalkGroup.style.display = provider === 'musetalk' ? 'block' : 'none';
  // wav2lip/mock 不需要 api-base
  // 自动填充默认地址
  if (_presets && _presets.avatar[provider]) {
    const preset = _presets.avatar[provider];
    if (preset.default_api_base && showApiBase) {
      const cur = document.getElementById('avatar-api-base').value;
      if (!cur) document.getElementById('avatar-api-base').value = preset.default_api_base;
    }
  }
  // 联动 pose 控件状态：仅 LongCat 引擎支持非 half_body 姿态
  updatePoseControlState(provider);
}

// 更新 pose 控件禁用状态（仅 LongCat 引擎消费 pose 字段）
// provider: 'wav2lip' | 'musetalk' | 'longcat' | 'latentsync' | 'echomimic' | 'mock'
function updatePoseControlState(provider) {
  const poseEnabled = provider === 'longcat';
  document.querySelectorAll('#scene-pose-grid .btn-card').forEach(btn => {
    if (btn.dataset.value === 'half_body') return;  // half_body 始终可用
    if (poseEnabled) {
      btn.disabled = false;
      btn.title = '仅 LongCat 引擎生效';
      const label = btn.querySelector('.btn-card-label');
      if (label) {
        label.textContent = label.textContent.replace(' (即将支持)', '').replace(' (仅 LongCat 支持)', '');
      }
    } else {
      btn.disabled = true;
      btn.title = '仅 LongCat 引擎支持';
      const label = btn.querySelector('.btn-card-label');
      if (label && !label.textContent.includes('仅 LongCat 支持')) {
        label.textContent = label.textContent.replace(' (即将支持)', '') + ' (仅 LongCat 支持)';
      }
    }
  });
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
  // LongCat 配置
  data.longcat = {
    server_url: document.getElementById('longcat-server-url').value.trim(),
    api_key: document.getElementById('longcat-api-key').value.trim(),
    model_type: document.getElementById('longcat-model-type').value,
    resolution: document.getElementById('longcat-resolution').value,
    timeout: parseInt(document.getElementById('longcat-timeout').value) || 600,
  };
  // MuseTalk 配置
  data.musetalk = {
    server_url: document.getElementById('musetalk-server-url').value.trim(),
    api_key: document.getElementById('musetalk-api-key').value.trim(),
    version: document.getElementById('musetalk-version').value,
    use_float16: document.getElementById('musetalk-use-float16').value === 'true',
    fps: parseInt(document.getElementById('musetalk-fps').value) || 25,
    bbox_shift: parseInt(document.getElementById('musetalk-bbox-shift').value) || 5,
    timeout: 600,
  };
  try {
    const result = await api('/api/settings/avatar', {
      method: 'PUT', body: { section: 'avatar', data },
    });
    if (result.success) {
      toast('数字人配置已保存', 'success');
      _currentSettings = await api('/api/settings');
      updateModelStatusBadges();
      // 设置变更后使向导缓存失效，下次进入向导时重新加载设置回填
      if (typeof window !== 'undefined') window._wizardVoiceList = null;
      // 联动 P1：广播设置变更事件，通知向导实时刷新数字人配置（pose 启用状态等）
      window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'avatar' } }));
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
  const provider = document.getElementById('avatar-provider').value;
  const btn = document.getElementById('avatar-test-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 测试中...';

  // LongCat 走专用测试 API
  if (provider === 'longcat') {
    const serverUrl = document.getElementById('longcat-server-url').value.trim();
    const apiKey = document.getElementById('longcat-api-key').value.trim();
    if (!serverUrl) {
      showTestResult('avatar-test-result', { success: false, message: '请先填写 LongCat 服务器地址' });
      toast('请先填写服务器地址', 'error');
      btn.disabled = false;
      btn.innerHTML = '🔌 测试连接';
      return;
    }
    try {
      const result = await api('/api/avatar/longcat/test', {
        method: 'POST', body: { server_url: serverUrl, api_key: apiKey },
      });
      showTestResult('avatar-test-result', { success: result.ok, message: result.message });
      toast(result.ok ? 'LongCat 连接成功' : '连接失败', result.ok ? 'success' : 'error');
    } catch (e) {
      showTestResult('avatar-test-result', { success: false, message: e.message });
    } finally {
      btn.disabled = false;
      btn.innerHTML = '🔌 测试连接';
    }
    return;
  }

  // MuseTalk 走专用测试 API
  if (provider === 'musetalk') {
    const serverUrl = document.getElementById('musetalk-server-url').value.trim();
    const apiKey = document.getElementById('musetalk-api-key').value.trim();
    if (!serverUrl) {
      showTestResult('avatar-test-result', { success: false, message: '请先填写 MuseTalk 服务器地址' });
      toast('请先填写服务器地址', 'error');
      btn.disabled = false;
      btn.innerHTML = '🔌 测试连接';
      return;
    }
    try {
      const result = await api('/api/avatar/musetalk/test', {
        method: 'POST', body: { server_url: serverUrl, api_key: apiKey },
      });
      showTestResult('avatar-test-result', { success: result.ok, message: result.message });
      toast(result.ok ? 'MuseTalk 连接成功' : '连接失败', result.ok ? 'success' : 'error');
    } catch (e) {
      showTestResult('avatar-test-result', { success: false, message: e.message });
    } finally {
      btn.disabled = false;
      btn.innerHTML = '🔌 测试连接';
    }
    return;
  }

  // 其他 provider 走原有测试逻辑
  const payload = {
    provider: provider,
    api_base: document.getElementById('avatar-api-base').value,
  };
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
    // 设置变更后使向导缓存失效，下次进入向导时重新加载设置回填（字幕/BGM/视频输出）
    if (typeof window !== 'undefined') window._wizardVoiceList = null;
    // 联动 P1：广播设置变更事件，通知向导实时刷新字幕/BGM/视频输出配置
    window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'video' } }));
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
  // 强制重新获取最新配置，避免使用缓存的旧数据（修复背景颜色等字段不回写问题）
  _currentSettings = await api('/api/settings');
  const scene = _currentSettings.scene || {};
  const audio = _currentSettings.audio || {};
  const effects = _currentSettings.effects || {};

  let presets;
  try { presets = await ensureCreativePresets(); } catch (e) { presets = null; }

  // 数字人场景
  if (presets) {
    renderBtnCardGrid('scene-pose-grid', presets.poses, POSE_ICONS);
    // pose 控件禁用状态：仅 LongCat 引擎支持非 half_body 姿态
    const _avatarProvider = (document.getElementById('avatar-provider') || {}).value || 'mock';
    updatePoseControlState(_avatarProvider);
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
    // 设置变更后使向导缓存失效，下次进入向导时重新加载设置回填（场景/音频/效果）
    if (typeof window !== 'undefined') window._wizardVoiceList = null;
    // 联动 P1：广播设置变更事件，通知向导实时刷新场景/音频/效果配置
    window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'scene' } }));
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

  // 初始化 账号管理 + 一键发布 + 发布历史
  loadAccountsStatus();        // 新：账号管理区（替代 loadCookieManager）
  loadCookieManager();         // 保留：高级选项中的手动 Cookie 管理
  loadPublishJobSelect();      // 修改：默认选最新视频
  loadPublishPlatformsGrid();  // 修改：只显示已登录平台
  loadPublishHistory();        // 新：发布历史
  loadTestVideoSelect();
  const publishRunBtn = document.getElementById('publish-run-btn');
  if (publishRunBtn) publishRunBtn.addEventListener('click', runPublishVideo);

  // 发布测试台按钮绑定
  document.getElementById('test-cookies-btn')?.addEventListener('click', runTestCookies);
  document.getElementById('test-login-btn')?.addEventListener('click', runTestLogin);
  document.getElementById('test-selectors-btn')?.addEventListener('click', runTestSelectors);
  document.getElementById('test-upload-btn')?.addEventListener('click', runTestUpload);
}

function togglePlatform(key, el) {
  el.classList.toggle('active');
}

// ========== 账号管理（一次登录，永久复用） ==========

async function loadAccountsStatus() {
  const gridEl = document.getElementById('accounts-grid');
  if (!gridEl) return;
  gridEl.innerHTML = '<div style="color:#666;font-size:12px;padding:8px">加载中...</div>';
  try {
    const result = await api('/api/publish/cookies');
    const cookies = result.cookies || {};
    // 第1步：快速渲染 Cookie 文件状态（已配置显示"校验中..."，未配置显示"未登录"）
    gridEl.innerHTML = Object.entries(PLATFORM_INFO).map(([key, info]) => {
      const c = cookies[key] || {};
      const configured = c.configured;
      const loginBtnLabel = configured ? '重新登录' : (key === 'bilibili' ? '扫码登录' : '浏览器登录');
      const loginBtn = key === 'bilibili'
        ? `<button class="btn btn-sm btn-primary bilibili-login-btn" onclick="loginBilibiliQrcode()">${loginBtnLabel}</button>`
        : `<button class="btn btn-sm btn-primary" onclick="loginBrowserPlatform('${key}')">${loginBtnLabel}</button>`;
      // 已配置的先显示"校验中..."，未配置的显示"未登录"
      const statusBadge = configured
        ? '<span class="badge badge-info" id="status-' + key + '">⏳ 校验中...</span>'
        : '<span class="badge badge-muted">✗ 未登录</span>';
      const deleteBtn = configured
        ? `<button class="btn btn-sm btn-secondary" onclick="deleteCookie('${key}')" title="退出登录">退出</button>`
        : '';
      const cardBorder = configured ? 'var(--border-default)' : 'var(--border-default)';
      return `
        <div class="cookie-mgr-card" data-platform="${key}" id="card-${key}" style="padding:14px;border:1px solid ${cardBorder};border-radius:var(--radius-md);background:var(--bg-elevated)">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="font-size:24px">${info.icon}</span>
            <div>
              <div style="font-weight:600;font-size:14px">${info.name}</div>
              ${statusBadge}
            </div>
          </div>
          <div style="display:flex;gap:6px">
            ${loginBtn}
            ${deleteBtn}
          </div>
        </div>
      `;
    }).join('');

    // 第2步：对已配置平台，并行调用 login_check API 做真实校验
    const configuredPlatforms = Object.entries(PLATFORM_INFO)
      .filter(([key]) => cookies[key]?.configured)
      .map(([key]) => key);

    if (configuredPlatforms.length === 0) return;

    // 并行校验所有已配置平台
    const checkPromises = configuredPlatforms.map(async (platform) => {
      try {
        const result = await api('/api/publish/test/login_check', {
          method: 'POST',
          body: { platform },
        });
        return { platform, result };
      } catch (e) {
        return { platform, result: { success: false, error: e.message } };
      }
    });

    // 逐个更新状态徽章（哪个先返回就先更新）
    checkPromises.forEach(async (promise) => {
      const { platform, result } = await promise;
      const badgeEl = document.getElementById(`status-${platform}`);
      const cardEl = document.getElementById(`card-${platform}`);
      // 更新全局登录态缓存
      _platformLoginStatus[platform] = result;

      if (!badgeEl || !cardEl) {
        // 账号管理区可能未渲染，但仍然刷新一键发布区
        loadPublishPlatformsGrid();
        return;
      }

      if (!result.success) {
        // 校验请求失败
        badgeEl.className = 'badge badge-warning';
        badgeEl.textContent = '⚠ 校验失败';
        cardEl.style.borderColor = '#f57c00';
      } else if (result.logged_in) {
        // 登录态有效
        badgeEl.className = 'badge badge-success';
        badgeEl.textContent = '✓ 已登录';
        cardEl.style.borderColor = '#2e7d32';
      } else {
        // 登录态失效（关键修复：显示红色警示，指导用户重新登录）
        badgeEl.className = 'badge badge-error';
        const reason = result.has_login_form ? 'Cookie已失效'
          : (result.upload_link_to_login ? '登录态已过期'
          : '未真正登录');
        badgeEl.textContent = '⚠ ' + reason;
        cardEl.style.borderColor = '#c62828';
        cardEl.style.background = '#ffebee';
        // 高亮"重新登录"按钮
        const loginBtn = cardEl.querySelector('button.btn-primary');
        if (loginBtn) {
          loginBtn.style.background = '#c62828';
          loginBtn.style.border = '1px solid #c62828';
          loginBtn.textContent = '重新登录';
        }
      }
      // 每个平台校验完成后，刷新一键发布区的平台多选
      loadPublishPlatformsGrid();
    });
  } catch (e) {
    gridEl.innerHTML = `<div class="hint">加载失败: ${e.message}</div>`;
  }
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
        ? `<button class="btn btn-sm btn-primary bilibili-login-btn" onclick="loginBilibiliQrcode()">扫码登录</button>`
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
          ${key === 'bilibili' ? '<div class="bilibili-qrcode-hint" style="text-align:center;margin-top:8px;font-size:11px;color:var(--text-secondary)">点击"扫码登录"按钮，弹出二维码窗口</div>' : ''}
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
  // 禁用所有 B站登录按钮（用 class 选择，避免 id 重复问题）
  const btns = document.querySelectorAll('.bilibili-login-btn');
  btns.forEach(b => { b.disabled = true; b.innerHTML = '<span class="spinner"></span> 获取二维码...'; });
  // 弹出模态弹窗显示二维码（统一入口，避免二维码渲染到不可见区域）
  _showBilibiliQrcodeModal('正在获取二维码...', null);
  try {
    const result = await api('/api/publish/login/bilibili/qrcode', { method: 'POST' });
    if (!result.qrcode_image && !result.qrcode_url) throw new Error('未获取到二维码');
    // 渲染二维码到弹窗
    const imgSrc = result.qrcode_image
      ? `data:image/png;base64,${result.qrcode_image}`
      : result.qrcode_url;
    _showBilibiliQrcodeModal('请用哔哩哔哩APP扫描二维码登录', imgSrc);
    btns.forEach(b => { b.disabled = false; b.innerHTML = '等待扫码...'; b.disabled = true; });
    // 轮询检查扫码状态
    _bilibiliLoginPolling = true;
    _pollBilibiliLogin();
  } catch (e) {
    toast(`B站扫码登录失败: ${e.message}`, 'error');
    _hideBilibiliQrcodeModal();
    btns.forEach(b => { b.disabled = false; b.innerHTML = '扫码登录'; });
  }
}

function _showBilibiliQrcodeModal(hintText, imgSrc) {
  let modal = document.getElementById('bilibili-qrcode-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'bilibili-qrcode-modal';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(8px);z-index:9999;display:flex;align-items:center;justify-content:center';
    modal.innerHTML = `
      <div style="background:var(--bg-surface,#fff);border-radius:12px;padding:24px;width:360px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,0.18);position:relative">
        <button type="button" id="bilibili-qrcode-close" style="position:absolute;top:8px;right:8px;background:rgba(0,0,0,0.1);border:none;font-size:18px;color:var(--text-primary);cursor:pointer;padding:4px 10px;line-height:1;border-radius:6px">✕</button>
        <h3 style="font-size:16px;font-weight:600;margin:0 0 16px 0;text-align:center">哔哩哔哩扫码登录</h3>
        <div id="bilibili-qrcode-modal-hint" style="font-size:13px;color:var(--text-secondary);text-align:center;margin-bottom:12px"></div>
        <div id="bilibili-qrcode-modal-img" style="text-align:center"></div>
        <div id="bilibili-qrcode-modal-status" style="font-size:11px;color:var(--text-secondary);text-align:center;margin-top:8px">等待扫码确认...</div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.querySelector('#bilibili-qrcode-close').addEventListener('click', () => {
      _bilibiliLoginPolling = false;
      _hideBilibiliQrcodeModal();
      const btns = document.querySelectorAll('.bilibili-login-btn');
      btns.forEach(b => { b.disabled = false; b.innerHTML = '扫码登录'; });
    });
  }
  modal.style.display = 'flex';
  modal.querySelector('#bilibili-qrcode-modal-hint').textContent = hintText;
  const imgContainer = modal.querySelector('#bilibili-qrcode-modal-img');
  if (imgSrc) {
    imgContainer.innerHTML = `<img src="${imgSrc}" style="max-width:240px;border:1px solid var(--border-default);border-radius:8px" />`;
  } else {
    imgContainer.innerHTML = '<div style="padding:40px"><span class="spinner" style="margin:0 auto"></span></div>';
  }
}

function _hideBilibiliQrcodeModal() {
  const modal = document.getElementById('bilibili-qrcode-modal');
  if (modal) modal.style.display = 'none';
}

function _updateBilibiliQrcodeModalStatus(text, isSuccess, isError) {
  const statusEl = document.querySelector('#bilibili-qrcode-modal-status');
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.style.color = isSuccess ? 'var(--color-success)' : (isError ? 'var(--color-error)' : 'var(--text-secondary)');
}

async function _pollBilibiliLogin() {
  if (!_bilibiliLoginPolling) return;
  try {
    const result = await api('/api/publish/login/bilibili/check');
    if (result.status === 'success' || result.success) {
      _bilibiliLoginPolling = false;
      _updateBilibiliQrcodeModalStatus('✓ 登录成功，Cookie已自动保存', true, false);
      toast('B站登录成功！Cookie已自动保存', 'success');
      // 2秒后关闭弹窗
      setTimeout(() => _hideBilibiliQrcodeModal(), 2000);
      const btns = document.querySelectorAll('.bilibili-login-btn');
      btns.forEach(b => { b.disabled = false; b.innerHTML = '重新登录'; });
      // 清空该平台的登录态缓存，触发重新校验
      delete _platformLoginStatus['bilibili'];
      loadCookieManager();
      loadAccountsStatus();
      loadPublishPlatformsGrid();
      return;
    }
    if (result.status === 'expired' || result.status === 'failed') {
      _bilibiliLoginPolling = false;
      _updateBilibiliQrcodeModalStatus('二维码已过期，请关闭后重新扫码', false, true);
      toast('二维码已过期，请重新扫码', 'error');
      const btns = document.querySelectorAll('.bilibili-login-btn');
      btns.forEach(b => { b.disabled = false; b.innerHTML = '扫码登录'; });
      return;
    }
    // 继续轮询（每2秒）
    setTimeout(_pollBilibiliLogin, 2000);
  } catch (e) {
    _bilibiliLoginPolling = false;
    _updateBilibiliQrcodeModalStatus(`检查扫码状态失败: ${e.message}`, false, true);
    const btns = document.querySelectorAll('.bilibili-login-btn');
    btns.forEach(b => { b.disabled = false; b.innerHTML = '扫码登录'; });
    toast(`检查扫码状态失败: ${e.message}`, 'error');
  }
}

// 浏览器自动登录（抖音/快手/视频号）
async function loginBrowserPlatform(platform) {
  const platformName = PLATFORM_INFO[platform]?.name || platform;
  // 关键提示：告知用户在弹出的浏览器中登录，最长等待5分钟
  toast(`正在打开浏览器登录${platformName}...请在弹出的浏览器窗口中完成登录`, 'info', 8000);
  // 显示进度提示
  const cardEl = document.getElementById(`card-${platform}`);
  const badgeEl = document.getElementById(`status-${platform}`);
  if (badgeEl) {
    badgeEl.className = 'badge badge-info';
    badgeEl.textContent = '⏳ 等待登录...';
  }
  if (cardEl) {
    const loginBtn = cardEl.querySelector('button.btn-primary');
    if (loginBtn) {
      loginBtn.disabled = true;
      loginBtn.innerHTML = '<span class="spinner"></span> 等待登录...';
    }
  }

  try {
    const result = await api(`/api/publish/login/${platform}`, { method: 'POST' });
    if (result.success || result.status === 'success') {
      toast(`${platformName}登录成功！已保存 ${result.cookie_count || ''} 个Cookie`, 'success', 5000);
      // 清空该平台的登录态缓存，触发重新校验
      delete _platformLoginStatus[platform];
      loadCookieManager();
      loadAccountsStatus();  // 会自动重新校验登录态
      loadPublishPlatformsGrid();
    } else {
      toast(`${platformName}登录未完成: ${result.message || result.error || '可能超时或用户取消'}`, 'error', 8000);
      // 恢复按钮状态
      if (cardEl) {
        const loginBtn = cardEl.querySelector('button.btn-primary');
        if (loginBtn) {
          loginBtn.disabled = false;
          loginBtn.innerHTML = '重新登录';
        }
      }
      // 恢复状态徽章
      if (badgeEl) {
        badgeEl.className = 'badge badge-error';
        badgeEl.textContent = '⚠ 登录失败';
      }
    }
  } catch (e) {
    toast(`${platformName}浏览器登录失败: ${e.message}`, 'error', 8000);
    // 恢复按钮状态
    if (cardEl) {
      const loginBtn = cardEl.querySelector('button.btn-primary');
      if (loginBtn) {
        loginBtn.disabled = false;
        loginBtn.innerHTML = '重新登录';
      }
    }
    if (badgeEl) {
      badgeEl.className = 'badge badge-error';
      badgeEl.textContent = '⚠ 登录失败';
    }
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
    loadAccountsStatus();
    loadPublishPlatformsGrid();
  } catch (e) {
    toast(`保存失败: ${e.message}`, 'error');
  }
}

async function deleteCookie(platform) {
  if (!confirm(`确定删除 ${PLATFORM_INFO[platform].name} 的 Cookie？`)) return;
  try {
    await api(`/api/publish/cookies/${platform}`, { method: 'DELETE' });
    toast('Cookie 已删除', 'success');
    // 清空该平台的登录态缓存
    delete _platformLoginStatus[platform];
    loadCookieManager();
    loadAccountsStatus();
    loadPublishPlatformsGrid();
  } catch (e) {
    toast(`删除失败: ${e.message}`, 'error');
  }
}

async function loadPublishJobSelect() {
  const sel = document.getElementById('publish-job-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">-- 加载中... --</option>';
  try {
    const jobs = await api('/api/jobs?limit=20');
    const jobList = jobs.jobs || jobs || [];
    const successJobs = jobList.filter(j => j.status === 'success');
    // 批量查询详情获取 video_path
    const detailReqs = successJobs.map(j => api(`/api/jobs/${j.job_id}`));
    const details = await Promise.all(detailReqs);
    const completed = details.map((d, i) => {
      const output = d.output || {};
      const videoPath = output.final_video_absolute || output.video_path_absolute ||
                        output.final_video || output.video_path || '';
      return {
        job_id: successJobs[i].job_id,
        video_path: videoPath,
        title: output.title || '',
      };
    }).filter(j => j.video_path);

    if (completed.length === 0) {
      sel.innerHTML = '<option value="">-- 暂无已完成视频，请先生成视频 --</option>';
      return;
    }
    sel.innerHTML = '<option value="">-- 选择视频 --</option>' +
      completed.map(j => {
        const videoName = (j.video_path || '').split(/[\\/]/).pop() || '';
        const label = j.title ? `${j.title.slice(0, 30)} (${j.job_id})` : `${j.job_id} · ${videoName}`;
        return `<option value="${j.job_id}" data-video-path="${j.video_path}">${label}</option>`;
      }).join('');
    // 默认选第一个（最新视频，jobs 已按 created_at DESC 排序）
    if (completed.length > 0) {
      sel.value = completed[0].job_id;
    }
  } catch (e) {
    sel.innerHTML = `<option value="">加载失败: ${e.message}</option>`;
  }
}

async function loadPublishPlatformsGrid() {
  const grid = document.getElementById('publish-platforms-grid');
  const emptyEl = document.getElementById('publish-platforms-empty');
  if (!grid) return;
  try {
    const result = await api('/api/publish/cookies');
    const cookies = result.cookies || {};

    // 基于真实登录态判断（优先用 _platformLoginStatus 缓存，回退到 Cookie 文件判断）
    // 关键修复：只显示真正登录有效的平台，避免用户勾选失效平台导致发布失败
    const validPlatforms = [];
    const pendingPlatforms = [];  // 校验中的平台
    Object.entries(PLATFORM_INFO).forEach(([key]) => {
      const configured = cookies[key]?.configured;
      if (!configured) return;
      const loginStatus = _platformLoginStatus[key];
      if (!loginStatus) {
        // 未校验完，先加入待定列表（初始展示，但后续会被刷新）
        pendingPlatforms.push(key);
      } else if (loginStatus.success && loginStatus.logged_in) {
        validPlatforms.push(key);
      }
      // 校验失败或登录态失效的平台不显示
    });

    // 如果还没有任何校验结果，先用 pendingPlatforms（避免页面空白）
    const displayPlatforms = validPlatforms.length > 0 ? validPlatforms : pendingPlatforms;

    if (displayPlatforms.length === 0) {
      grid.innerHTML = '';
      if (emptyEl) {
        emptyEl.style.display = 'block';
        // 区分"未配置任何平台" vs "已配置但都失效"
        const anyConfigured = Object.values(cookies).some(c => c.configured);
        if (anyConfigured) {
          emptyEl.innerHTML = '⚠ 所有已配置平台的登录态均已失效，请先在上方"账号管理"中重新登录';
          emptyEl.style.background = '#ffebee';
          emptyEl.style.borderColor = '#ef9a9a';
          emptyEl.style.color = '#c62828';
        } else {
          emptyEl.innerHTML = '⚠ 暂无已登录平台，请先在上方"账号管理"中登录至少一个平台';
          emptyEl.style.background = '#fff3e0';
          emptyEl.style.borderColor = '#ffe082';
          emptyEl.style.color = '#8b6914';
        }
      }
    } else {
      if (emptyEl) emptyEl.style.display = 'none';
      grid.innerHTML = displayPlatforms.map(key => {
        const info = PLATFORM_INFO[key];
        return `
          <label class="matrix-checkbox-item">
            <input type="checkbox" value="${key}" checked>
            <span>${info.icon} ${info.name}</span>
          </label>
        `;
      }).join('');
    }
  } catch (e) {
    grid.innerHTML = `<div class="hint">加载失败: ${e.message}</div>`;
  }
}

// ========== 发布历史（localStorage 存储） ==========

function loadPublishHistory() {
  const listEl = document.getElementById('publish-history-list');
  if (!listEl) return;
  try {
    const history = JSON.parse(localStorage.getItem('enlyai_publish_history') || '[]');
    if (history.length === 0) {
      listEl.innerHTML = '<div style="padding:12px;color:#666;font-size:13px;text-align:center">暂无发布记录</div>';
      return;
    }
    listEl.innerHTML = history.slice(0, 5).map(h => {
      const info = PLATFORM_INFO[h.platform] || { name: h.platform, icon: '' };
      const ok = h.status === 'success';
      const color = ok ? '#2e7d32' : (h.status === 'skipped' ? '#f57c00' : '#c62828');
      const bg = ok ? '#e8f5e9' : (h.status === 'skipped' ? '#fff3e0' : '#ffebee');
      return `
        <div style="padding:10px;background:${bg};border-radius:6px;margin-bottom:6px;font-size:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span><strong>${info.icon} ${info.name}</strong> · ${h.title || '未命名'}</span>
            <span style="color:${color};font-weight:600">${ok ? '✓ 已发布' : (h.status === 'skipped' ? '⚠ 跳过' : '✗ 失败')}</span>
          </div>
          <div style="color:#666;margin-top:4px;display:flex;justify-content:space-between">
            <span>${h.time || ''}</span>
            ${h.url ? `<a href="${h.url}" target="_blank" style="color:var(--accent-primary)">查看视频 →</a>` : ''}
          </div>
          ${h.error ? `<div style="color:#c62828;margin-top:4px">错误: ${escapeHtml(h.error)}</div>` : ''}
        </div>
      `;
    }).join('');
  } catch (e) {
    listEl.innerHTML = `<div class="hint">加载历史失败: ${e.message}</div>`;
  }
}

function savePublishHistory(record) {
  try {
    const history = JSON.parse(localStorage.getItem('enlyai_publish_history') || '[]');
    history.unshift(record);
    localStorage.setItem('enlyai_publish_history', JSON.stringify(history.slice(0, 20)));
    loadPublishHistory();
  } catch (e) {
    console.error('保存发布历史失败:', e);
  }
}

// ============ 发布测试台（4 阶段测试链路） ============

async function loadTestVideoSelect() {
  const sel = document.getElementById('test-video-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">-- 加载中... --</option>';
  try {
    const jobs = await api('/api/jobs?limit=20');
    const jobList = jobs.jobs || jobs || [];
    // list_jobs 仅返回 job_id/status，需对 success 任务调用详情 API 获取 video_path
    const successJobs = jobList.filter(j => j.status === 'success');
    const detailReqs = successJobs.map(j => api(`/api/jobs/${j.job_id}`));
    const details = await Promise.all(detailReqs);
    // 从 output 中提取 video_path 或 final_video（绝对路径优先）
    const completed = details.map((d, i) => {
      const output = d.output || {};
      const videoPath = output.final_video_absolute || output.video_path_absolute ||
                        output.final_video || output.video_path || '';
      return { job_id: successJobs[i].job_id, video_path: videoPath };
    }).filter(j => j.video_path);
    if (completed.length === 0) {
      sel.innerHTML = '<option value="">-- 暂无已完成视频 --</option>';
      return;
    }
    sel.innerHTML = '<option value="">-- 选择测试视频 --</option>' +
      completed.map(j => {
        const videoName = (j.video_path || '').split(/[\\/]/).pop() || '';
        return `<option value="${j.video_path}">${j.job_id} · ${videoName}</option>`;
      }).join('');
  } catch (e) {
    sel.innerHTML = `<option value="">加载失败: ${e.message}</option>`;
  }
}

function _renderTestResult(result, title) {
  const el = document.getElementById('test-result');
  if (!el) return;
  const success = result.success !== false;
  const bgColor = success ? '#e8f5e9' : '#ffebee';
  const borderColor = success ? '#81c784' : '#e57373';
  const titleColor = success ? '#2e7d32' : '#c62828';

  let detailHtml = '';
  if (result.platforms) {
    // Cookie 检查结果（多平台）
    detailHtml = Object.entries(result.platforms).map(([key, info]) => {
      const valid = info.valid;
      const bg = valid ? '#e8f5e9' : (info.file_exists ? '#fff3e0' : '#ffebee');
      const color = valid ? '#2e7d32' : (info.file_exists ? '#e65100' : '#c62828');
      let detail = '';
      if (info.file_exists) {
        detail = `Cookie 数量: ${info.cookie_count || 0}`;
        if (info.missing_fields && info.missing_fields.length > 0) {
          detail += ` | 缺失字段: ${info.missing_fields.join(', ')}`;
        }
      } else {
        detail = info.error || '文件不存在';
      }
      return `
        <div style="padding:8px;margin:4px 0;background:${bg};border-radius:4px;font-size:12px">
          <strong style="color:${color}">${PLATFORM_INFO[key]?.name || key}: ${valid ? '✓ 有效' : (info.file_exists ? '⚠ 不完整' : '✗ 不存在')}</strong>
          <div style="color:#666;margin-top:2px">${detail}</div>
        </div>`;
    }).join('');
  } else if (result.selectors) {
    // 选择器探测结果
    detailHtml = Object.entries(result.selectors).map(([name, s]) => {
      const bg = s.found ? '#e8f5e9' : '#ffebee';
      const color = s.found ? '#2e7d32' : '#c62828';
      return `
        <div style="padding:6px;margin:4px 0;background:${bg};border-radius:4px;font-size:12px">
          <strong style="color:${color}">${name}: ${s.found ? '✓ 找到' : '✗ 未找到'} (${s.count || 0})</strong>
          <div style="color:#666;margin-top:2px;font-family:monospace">${s.selector}</div>
        </div>`;
    }).join('');
  } else {
    // 单平台结果
    detailHtml = `<pre style="margin:4px 0;padding:8px;background:#f5f5f5;border-radius:4px;font-size:11px;overflow-x:auto;white-space:pre-wrap">${JSON.stringify(result, null, 2)}</pre>`;
  }

  el.innerHTML = `
    <div style="padding:12px;background:${bgColor};border:1px solid ${borderColor};border-radius:6px">
      <div style="font-weight:600;color:${titleColor};margin-bottom:6px">${title} ${success ? '✓' : '✗'}</div>
      ${result.message ? `<div style="font-size:13px;margin-bottom:6px">${result.message}</div>` : ''}
      ${detailHtml}
    </div>
  `;
}

async function runTestCookies() {
  const btn = document.getElementById('test-cookies-btn');
  const resultEl = document.getElementById('test-result');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 检查中...';
  resultEl.innerHTML = '<div style="color:#666;font-size:13px;padding:8px">正在检查所有平台 Cookie 文件...</div>';
  try {
    const result = await api('/api/publish/test/cookies');
    _renderTestResult(result, '1. Cookie 文件检查');
  } catch (e) {
    _renderTestResult({ success: false, message: e.message }, '1. Cookie 文件检查');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="file-check"></i> 1.Cookie检查';
    if (window.lucide) lucide.createIcons();
  }
}

async function runTestLogin() {
  const btn = document.getElementById('test-login-btn');
  const resultEl = document.getElementById('test-result');
  const platform = document.getElementById('test-platform-select').value;
  if (!platform) { toast('请选择测试平台', 'error'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 校验中...';
  resultEl.innerHTML = `<div style="color:#666;font-size:13px;padding:8px">正在校验 ${PLATFORM_INFO[platform]?.name || platform} 登录态（可能需要 10-30 秒）...</div>`;
  try {
    const result = await api('/api/publish/test/login_check', {
      method: 'POST', body: { platform },
    });
    _renderTestResult(result, `2. 登录态校验 - ${PLATFORM_INFO[platform]?.name || platform}`);
  } catch (e) {
    _renderTestResult({ success: false, message: e.message }, `2. 登录态校验 - ${PLATFORM_INFO[platform]?.name || platform}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="log-in"></i> 2.登录态校验';
    if (window.lucide) lucide.createIcons();
  }
}

async function runTestSelectors() {
  const btn = document.getElementById('test-selectors-btn');
  const resultEl = document.getElementById('test-result');
  const platform = document.getElementById('test-platform-select').value;
  if (!platform) { toast('请选择测试平台', 'error'); return; }
  if (platform === 'bilibili') { toast('B站走 API 无需选择器探测，请选择其他平台', 'error'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 探测中...';
  resultEl.innerHTML = `<div style="color:#666;font-size:13px;padding:8px">正在探测 ${PLATFORM_INFO[platform]?.name || platform} 页面选择器（将打开浏览器，请勿关闭）...</div>`;
  try {
    const result = await api('/api/publish/test/selectors', {
      method: 'POST', body: { platform },
    });
    _renderTestResult(result, `3. 选择器探测 - ${PLATFORM_INFO[platform]?.name || platform}`);
  } catch (e) {
    _renderTestResult({ success: false, message: e.message }, `3. 选择器探测 - ${PLATFORM_INFO[platform]?.name || platform}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="search"></i> 3.选择器探测';
    if (window.lucide) lucide.createIcons();
  }
}

async function runTestUpload() {
  const btn = document.getElementById('test-upload-btn');
  const resultEl = document.getElementById('test-result');
  const platform = document.getElementById('test-platform-select').value;
  const videoPath = document.getElementById('test-video-select').value;
  const title = document.getElementById('test-video-title').value.trim();
  const dryRun = document.getElementById('test-dry-run').checked;

  if (!platform) { toast('请选择测试平台', 'error'); return; }
  if (!videoPath) { toast('请选择测试视频', 'error'); return; }

  if (!dryRun) {
    if (!confirm(`确认要真实发布视频到 ${PLATFORM_INFO[platform]?.name || platform} 吗？\n\n此操作将点击发布按钮，视频将真实发布到平台！`)) {
      return;
    }
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 上传中...';
  resultEl.innerHTML = `<div style="color:#666;font-size:13px;padding:8px">正在上传视频到 ${PLATFORM_INFO[platform]?.name || platform}（${dryRun ? 'dry-run 模式' : '真实发布模式'}，可能需要 1-5 分钟）...</div>`;
  try {
    const result = await api('/api/publish/test/upload', {
      method: 'POST',
      body: { platform, video_path: videoPath, dry_run: dryRun, title, description: '' },
    });
    _renderTestResult(result, `4. 上传测试 - ${PLATFORM_INFO[platform]?.name || platform} (${dryRun ? 'dry-run' : '真实发布'})`);
  } catch (e) {
    _renderTestResult({ success: false, message: e.message }, `4. 上传测试 - ${PLATFORM_INFO[platform]?.name || platform}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="upload-cloud"></i> 4.上传测试';
    if (window.lucide) lucide.createIcons();
  }
}

async function runPublishVideo() {
  const jobId = document.getElementById('publish-job-select').value;
  const platforms = Array.from(document.querySelectorAll('#publish-platforms-grid input:checked')).map(c => c.value);
  const title = document.getElementById('publish-title').value.trim();
  const description = document.getElementById('publish-description').value.trim();
  const tagsText = document.getElementById('publish-tags').value.trim();
  const resultEl = document.getElementById('publish-result');
  const btn = document.getElementById('publish-run-btn');

  if (!jobId) {
    toast('请先选择要发布的视频', 'error');
    return;
  }
  if (!platforms.length) {
    toast('请至少选择一个已登录平台（在上方"账号管理"中登录）', 'error');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 发布中...';
  resultEl.innerHTML = `<div style="color:#666;font-size:13px;padding:12px;background:#e3f2fd;border:1px solid #90caf9;border-radius:6px">
    <strong>正在发布到 ${platforms.length} 个平台...</strong><br>
    <span style="font-size:11px">可能需要 1-5 分钟，请勿关闭页面</span>
  </div>`;

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
      const now = new Date();
      const timeStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

      resultEl.innerHTML = `
        <div style="padding:12px;background:#e8f5e9;border:1px solid #81c784;border-radius:6px;margin-bottom:8px">
          <strong style="font-size:14px">✓ 发布完成：${successCount}/${totalCount} 平台成功</strong>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px">
          ${results.map(r => {
            const info = PLATFORM_INFO[r.platform] || { name: r.platform, icon: '' };
            const ok = r.status === 'success';
            const color = ok ? '#2e7d32' : (r.status === 'skipped' ? '#f57c00' : '#c62828');
            const bg = ok ? '#e8f5e9' : (r.status === 'skipped' ? '#fff3e0' : '#ffebee');
            const statusText = ok ? '✓ 已发布' : (r.status === 'skipped' ? '⚠ 跳过' : '✗ 失败');
            return `
              <div style="padding:10px;background:${bg};border-radius:6px;font-size:13px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span><strong>${info.icon} ${info.name}</strong></span>
                  <span style="color:${color};font-weight:600">${statusText}</span>
                </div>
                ${r.url ? `<div style="margin-top:6px"><a href="${r.url}" target="_blank" style="color:var(--accent-primary);font-size:12px">查看视频 →</a></div>` : ''}
                ${r.error ? `<div style="color:#c62828;margin-top:4px;font-size:11px">错误: ${escapeHtml(r.error)}</div>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      `;
      toast(`发布完成：${successCount}/${totalCount} 成功`, successCount === totalCount ? 'success' : 'info');

      // 保存到发布历史
      results.forEach(r => {
        savePublishHistory({
          platform: r.platform,
          title: title || jobId,
          status: r.status,
          url: r.url || '',
          error: r.error || '',
          time: timeStr,
        });
      });
    } else {
      resultEl.innerHTML = `<div style="padding:12px;background:#ffebee;border:1px solid #ef9a9a;border-radius:6px;color:#c62828">
        <strong>发布失败：</strong>${escapeHtml(result.error || '未知错误')}
      </div>`;
      toast('发布失败', 'error');
    }
  } catch (e) {
    resultEl.innerHTML = `<div style="padding:12px;background:#ffebee;border:1px solid #ef9a9a;border-radius:6px;color:#c62828">
      <strong>请求失败：</strong>${escapeHtml(e.message)}
    </div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="send"></i> 立即发布';
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
      // 设置变更后使向导缓存失效，下次进入向导时重新加载发布设置回填
      if (typeof window !== 'undefined') window._wizardVoiceList = null;
      // 联动 P1：广播设置变更事件，通知向导实时刷新发布平台启用状态
      window.dispatchEvent(new CustomEvent('enlyai:settings-changed', { detail: { section: 'publisher' } }));
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
