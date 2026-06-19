/**
 * KrVoiceAI Web App
 * 前端交互逻辑
 */

const API_BASE = '';

// ========== 工具函数 ==========

async function api(path, options = {}) {
  const url = API_BASE + path;
  const opts = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
  }
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

function toast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  el.innerHTML = `<span style="font-size:18px">${icons[type] || ''}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'slideIn 0.3s ease reverse';
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

function formatTime(ts) {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function statusBadge(status) {
  const map = {
    success: ['badge-success', '成功'],
    failed: ['badge-error', '失败'],
    running: ['badge-info', '运行中'],
    pending: ['badge-warning', '等待中'],
    skipped: ['badge-muted', '跳过'],
    cancelled: ['badge-muted', '已取消'],
  };
  const [cls, label] = map[status] || ['badge-muted', status];
  return `<span class="badge ${cls}">${label}</span>`;
}

// ========== 页面导航 ==========

const PAGES = [
  'wizard', 'generate', 'script', 'step-by-step', 'batch',
  'avatars', 'voices', 'templates', 'jobs',
  'settings-models', 'settings-video', 'settings-scene', 'settings-publish',
  'health',
];

function navigate(page) {
  PAGES.forEach(p => {
    const pageEl = document.getElementById(`page-${p}`);
    const navEl = document.getElementById(`nav-${p}`);
    if (pageEl) pageEl.classList.remove('active');
    if (navEl) navEl.classList.remove('active');
  });
  const targetPage = document.getElementById(`page-${page}`);
  const targetNav = document.getElementById(`nav-${page}`);
  if (targetPage) targetPage.classList.add('active');
  if (targetNav) targetNav.classList.add('active');

  // 页面加载时刷新数据
  if (page === 'jobs') loadJobs();
  if (page === 'avatars') loadAvatars();
  if (page === 'voices') loadVoices();
  if (page === 'health') loadHealth();
  if (page === 'wizard') initWizard();
  if (page === 'templates') loadTemplatesCenter();
  if (page === 'generate') { loadAvatarsForSelect(); loadVoicesForSelect(); }
  if (page === 'step-by-step') { loadAvatarsForSelect2(); loadVoicesForSelect2(); }
  if (page === 'batch') { loadAvatarsForSelect3(); loadVoicesForSelect3(); }
  if (page === 'settings-models') loadAllSettings();
  if (page === 'settings-video') loadVideoSettings();
  if (page === 'settings-scene') loadSceneEffectSettings();
  if (page === 'settings-publish') loadPublishSettings();
}

// ========== ASS 颜色转换 ==========
// ASS 格式 &HBBGGRR（如 &H00FFFFFF 是白色）<-> HEX #RRGGBB

function assToHex(ass) {
  // &H00FFFFFF -> #FFFFFF（取后6位反转 BBGGRR -> RRGGBB）
  if (!ass) return '#FFFFFF';
  let s = String(ass).replace('&H', '').replace('&h', '');
  // 去掉前导的 alpha（如 00），保留后6位
  if (s.length === 8) s = s.slice(2);
  if (s.length !== 6) return '#FFFFFF';
  const bb = s.slice(0, 2);
  const gg = s.slice(2, 4);
  const rr = s.slice(4, 6);
  return '#' + rr + gg + bb;
}

function hexToAss(hex) {
  // #FFD040 -> &H0040D0FF（RRGGBB -> BBGGRR，前缀 &H00）
  if (!hex) return '&H00FFFFFF';
  let s = String(hex).replace('#', '');
  if (s.length !== 6) return '&H00FFFFFF';
  const rr = s.slice(0, 2);
  const gg = s.slice(2, 4);
  const bb = s.slice(4, 6);
  return '&H00' + bb + gg + rr;
}

// ========== 创作预设缓存 ==========
let _creativePresets = null;
let _bgmLibrary = null;
let _templatesCache = null;

async function ensureCreativePresets() {
  if (!_creativePresets) {
    _creativePresets = await api('/api/creative/presets');
  }
  return _creativePresets;
}

async function ensureBgmLibrary() {
  if (!_bgmLibrary) {
    _bgmLibrary = await api('/api/bgm/library');
  }
  return _bgmLibrary;
}

async function ensureTemplates() {
  if (!_templatesCache) {
    _templatesCache = await api('/api/templates');
  }
  return _templatesCache;
}

// ========== 通用 UI 辅助函数 ==========

function toggleCollapse(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  const shown = el.style.display !== 'none';
  el.style.display = shown ? 'none' : 'block';
  if (btn) btn.textContent = shown ? '展开' : '收起';
}

// 绑定按钮卡片网格单选：点击切换 active，同组互斥
function bindBtnCardGrid(gridId, onSelect) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.querySelectorAll('.btn-card').forEach(btn => {
    btn.addEventListener('click', () => {
      grid.querySelectorAll('.btn-card').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (onSelect) onSelect(btn.dataset.value);
    });
  });
}

// 获取按钮卡片网格当前选中值
function getBtnCardValue(gridId) {
  const grid = document.getElementById(gridId);
  if (!grid) return null;
  const active = grid.querySelector('.btn-card.active');
  return active ? active.dataset.value : null;
}

// 设置按钮卡片网格选中值
function setBtnCardValue(gridId, value) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.querySelectorAll('.btn-card').forEach(b => {
    b.classList.toggle('active', b.dataset.value === value);
  });
}

// 渲染按钮卡片网格（从预设生成）
function renderBtnCardGrid(gridId, presets, iconMap) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.innerHTML = Object.entries(presets).map(([key, info]) => `
    <button class="btn-card" data-value="${key}" type="button">
      ${iconMap && iconMap[key] ? `<div class="btn-card-icon">${iconMap[key]}</div>` : ''}
      <div class="btn-card-label">${info.label}</div>
      <div class="btn-card-desc">${info.description || ''}</div>
    </button>
  `).join('');
}

// 渲染字幕样式预设网格
function renderSubtitleStyleGrid(gridId, presets, selectedKey, onSelect) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.innerHTML = Object.entries(presets).map(([key, info]) => {
    const color = assToHex(info.primary_color);
    const outline = assToHex(info.outline_color);
    const stroke = info.outline_width || 2;
    return `
      <div class="subtitle-style-card ${key === selectedKey ? 'active' : ''}" data-key="${key}">
        <div class="subtitle-style-preview" style="color:${color};text-shadow:-${stroke}px -${stroke}px 0 ${outline},${stroke}px -${stroke}px 0 ${outline},-${stroke}px ${stroke}px 0 ${outline},${stroke}px ${stroke}px 0 ${outline}">字幕示例</div>
        <div class="subtitle-style-name">${info.label}</div>
      </div>
    `;
  }).join('');
  grid.querySelectorAll('.subtitle-style-card').forEach(card => {
    card.addEventListener('click', () => {
      grid.querySelectorAll('.subtitle-style-card').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      if (onSelect) onSelect(card.dataset.key);
    });
  });
}

// 填充下拉选项（从预设）
function fillSelect(selectId, presets, valueKey) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  sel.innerHTML = Object.entries(presets).map(([key, info]) =>
    `<option value="${key}">${info.label}</option>`
  ).join('');
}

// ========== 创作向导 ==========

const POSE_ICONS = { standing: '🧍', sitting: '🪑', half_body: '🧍', closeup: '👤' };
const EMOTION_ICONS = { neutral: '😐', calm: '😌', excited: '🤩', gentle: '😊', serious: '😐', cheerful: '😄' };

let wizardState = {
  currentStep: 1,
  selectedTemplate: null,
  selectedSubtitleStyle: null,
  wizScriptTab: 'manual',
  wizScriptAction: 'polish',
  initialized: false,
};

function initWizard() {
  if (!wizardState.initialized) {
    wizardState.initialized = true;
    loadWizardData();
  }
}

async function loadWizardData() {
  try {
    const [presets, templates, bgmLib, avatars, voices] = await Promise.all([
      ensureCreativePresets(),
      ensureTemplates(),
      ensureBgmLibrary(),
      api('/api/avatars').catch(() => []),
      api('/api/voices').catch(() => []),
    ]);

    // 步骤1：模板网格
    renderWizardTemplateGrid(templates);

    // 步骤2：姿态网格
    renderBtnCardGrid('wiz-pose-grid', presets.poses, POSE_ICONS);
    setBtnCardValue('wiz-pose-grid', 'half_body');
    bindBtnCardGrid('wiz-pose-grid');
    bindBtnCardGrid('wiz-position-grid');
    bindBtnCardGrid('wiz-bg-type-grid', (val) => {
      document.getElementById('wiz-bg-color-group').style.display = val === 'solid' ? 'block' : 'none';
      document.getElementById('wiz-bg-image-group').style.display = val === 'image' ? 'block' : 'none';
    });

    // 形象/音色下拉
    const avatarIds = avatars.length ? avatars.map(a => a.avatar_id) : ['default'];
    const voiceIds = voices.length ? voices.map(v => v.voice_id) : ['default'];
    document.getElementById('wiz-avatar').innerHTML = avatarIds.map(id => `<option value="${id}">${id}</option>`).join('');
    document.getElementById('wiz-voice').innerHTML = voiceIds.map(id => `<option value="${id}">${id}</option>`).join('');

    // 步骤3：文案 Tab 切换
    document.querySelectorAll('[data-wiztab]').forEach(tab => {
      tab.addEventListener('click', () => {
        wizardState.wizScriptTab = tab.dataset.wiztab;
        document.querySelectorAll('[data-wiztab]').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('wiz-script-manual').classList.remove('active');
        document.getElementById('wiz-script-ai').classList.remove('active');
        document.getElementById('wiz-script-extract').classList.remove('active');
        document.getElementById('wiz-script-' + tab.dataset.wiztab).classList.add('active');
      });
    });

    // 文案 AI 处理动作
    document.querySelectorAll('[data-wizaction]').forEach(btn => {
      btn.addEventListener('click', () => {
        wizardState.wizScriptAction = btn.dataset.wizaction;
        document.querySelectorAll('[data-wizaction]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('wiz-style-group').style.display = btn.dataset.wizaction === 'style' ? 'block' : 'none';
      });
    });

    // 步骤4：情感网格
    renderBtnCardGrid('wiz-emotion-grid', presets.emotions, EMOTION_ICONS);
    setBtnCardValue('wiz-emotion-grid', 'neutral');
    bindBtnCardGrid('wiz-emotion-grid');

    // 步骤5：字幕样式预设
    renderSubtitleStyleGrid('wiz-subtitle-style-grid', presets.subtitle_styles, null, (key) => {
      wizardState.selectedSubtitleStyle = key;
      applySubtitleStylePreset(key);
    });
    fillSelect('wiz-sub-anim', presets.subtitle_animations);
    fillSelect('wiz-transition', presets.transitions);
    fillSelect('wiz-filter', presets.filters);

    // BGM 曲目
    const bgmSel = document.getElementById('wiz-bgm-track');
    bgmSel.innerHTML = Object.entries(bgmLib).map(([key, info]) =>
      `<option value="${key}">${info.label}（${info.mood}）</option>`
    ).join('');

    // 开关联动
    document.getElementById('wiz-show-logo').addEventListener('change', e => {
      document.getElementById('wiz-logo-position-group').style.display = e.target.checked ? 'block' : 'none';
    });
    document.getElementById('wiz-bgm-enabled').addEventListener('change', e => {
      document.getElementById('wiz-bgm-group').style.display = e.target.checked ? 'block' : 'none';
    });
    document.getElementById('wiz-watermark-enabled').addEventListener('change', e => {
      document.getElementById('wiz-watermark-group').style.display = e.target.checked ? 'block' : 'none';
    });

    // 文案字数统计
    document.getElementById('wiz-script').addEventListener('input', e => {
      document.getElementById('wiz-script-count').textContent = `${e.target.value.length} 字`;
    });

    // 绑定向导按钮
    document.getElementById('wizard-apply-template-btn').addEventListener('click', wizardApplyTemplate);
    document.getElementById('wizard-skip-template-btn').addEventListener('click', wizardSkipTemplate);
    document.getElementById('wiz-ai-generate-btn').addEventListener('click', wizardAiGenerate);
    document.getElementById('wiz-extract-btn').addEventListener('click', wizardExtractScript);
    document.getElementById('wiz-script-process-btn').addEventListener('click', wizardScriptProcess);
    document.getElementById('wiz-generate-btn').addEventListener('click', wizardGenerate);
    document.getElementById('wiz-prev-btn').addEventListener('click', () => wizardGoToStep(wizardState.currentStep - 1));
    document.getElementById('wiz-next-btn').addEventListener('click', wizardNext);

    renderWizardStepper();
    renderPipeline({}); // 初始化向导进度
    const wizPipeline = document.getElementById('wiz-pipeline');
    if (wizPipeline) wizPipeline.innerHTML = STEP_ORDER.map(step => {
      const info = STEP_INFO[step];
      return `<div class="pipeline-step pending"><div class="step-icon">○</div><div class="step-info"><div class="step-name">${info.icon} ${info.name}</div><div class="step-status">等待中</div></div></div>`;
    }).join('');
  } catch (e) {
    toast(`加载向导数据失败: ${e.message}`, 'error');
    console.error(e);
  }
}

function renderWizardTemplateGrid(templates) {
  const grid = document.getElementById('wizard-template-grid');
  if (!grid) return;
  grid.innerHTML = Object.entries(templates).map(([key, tpl]) => `
    <div class="template-card" data-key="${key}">
      <div class="template-card-icon">${tpl.icon}</div>
      <div class="template-card-label">${tpl.label}</div>
      <div class="template-card-desc">${tpl.description}</div>
      <div class="template-card-tags">
        <span class="template-card-tag">${tpl.subtitle_preset}</span>
        <span class="template-card-tag">${tpl.emotion}</span>
        <span class="template-card-tag">${tpl.filter}</span>
      </div>
    </div>
  `).join('');
  grid.querySelectorAll('.template-card').forEach(card => {
    card.addEventListener('click', () => {
      grid.querySelectorAll('.template-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      wizardState.selectedTemplate = card.dataset.key;
    });
  });
}

function renderWizardStepper() {
  const steps = document.querySelectorAll('.wizard-step');
  const lines = document.querySelectorAll('.wizard-step-line');
  steps.forEach((step, idx) => {
    const stepNum = parseInt(step.dataset.step);
    step.classList.remove('active', 'completed');
    if (stepNum < wizardState.currentStep) {
      step.classList.add('completed');
    } else if (stepNum === wizardState.currentStep) {
      step.classList.add('active');
    }
  });
  lines.forEach((line, idx) => {
    line.classList.toggle('completed', idx + 1 < wizardState.currentStep);
  });
  // 显示当前面板
  document.querySelectorAll('.wizard-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById(`wizard-panel-${wizardState.currentStep}`);
  if (panel) panel.classList.add('active');
  // 更新进度文本与按钮
  document.getElementById('wiz-progress-text').textContent = `第 ${wizardState.currentStep} / 6 步`;
  document.getElementById('wiz-prev-btn').disabled = wizardState.currentStep === 1;
  const nextBtn = document.getElementById('wiz-next-btn');
  if (wizardState.currentStep === 6) {
    nextBtn.innerHTML = '🚀 开始生成';
  } else {
    nextBtn.innerHTML = '下一步 →';
  }
  // 进入步骤6时渲染汇总
  if (wizardState.currentStep === 6) renderWizardSummary();
}

function wizardGoToStep(step) {
  if (step < 1 || step > 6) return;
  // 切换步骤前保存当前步骤配置
  wizardSaveCurrentStep();
  wizardState.currentStep = step;
  renderWizardStepper();
}

function wizardNext() {
  if (wizardState.currentStep >= 6) {
    wizardGenerate();
    return;
  }
  wizardSaveCurrentStep();
  wizardState.currentStep++;
  renderWizardStepper();
}

// 切换步骤时自动保存对应配置段
async function wizardSaveCurrentStep() {
  try {
    if (wizardState.currentStep === 2) {
      // scene 段
      const data = collectWizardScene();
      await api('/api/settings/scene', { method: 'PUT', body: { section: 'scene', data } });
    } else if (wizardState.currentStep === 4) {
      // audio 段（语音部分）
      const data = collectWizardAudio();
      await api('/api/settings/audio', { method: 'PUT', body: { section: 'audio', data } });
    } else if (wizardState.currentStep === 5) {
      // subtitle / audio(bgm) / effects 段
      await Promise.all([
        api('/api/settings/subtitle', { method: 'PUT', body: { section: 'subtitle', data: collectWizardSubtitle() } }),
        api('/api/settings/audio', { method: 'PUT', body: { section: 'audio', data: collectWizardAudioWithBgm() } }),
        api('/api/settings/effects', { method: 'PUT', body: { section: 'effects', data: collectWizardEffects() } }),
      ]);
    }
  } catch (e) {
    // 保存失败不阻塞流程，仅提示
    console.warn('向导步骤保存失败:', e.message);
  }
}

function collectWizardScene() {
  return {
    pose: getBtnCardValue('wiz-pose-grid') || 'half_body',
    position: getBtnCardValue('wiz-position-grid') || 'center',
    scale: parseFloat(document.getElementById('wiz-scale').value),
    background_type: getBtnCardValue('wiz-bg-type-grid') || 'transparent',
    background_color: document.getElementById('wiz-bg-color').value,
    background_image: document.getElementById('wiz-bg-image').value,
    show_logo: document.getElementById('wiz-show-logo').checked,
    logo_position: document.getElementById('wiz-logo-position').value,
  };
}

function collectWizardAudio() {
  return {
    speed: parseFloat(document.getElementById('wiz-speed').value),
    volume: parseInt(document.getElementById('wiz-volume').value),
    pitch: parseInt(document.getElementById('wiz-pitch').value),
    emotion: getBtnCardValue('wiz-emotion-grid') || 'neutral',
    pause_duration: parseFloat(document.getElementById('wiz-pause').value),
    remove_silence: document.getElementById('wiz-remove-silence').checked,
    voice_enhance: document.getElementById('wiz-voice-enhance').checked,
  };
}

function collectWizardAudioWithBgm() {
  const audio = collectWizardAudio();
  audio.bgm = {
    enabled: document.getElementById('wiz-bgm-enabled').checked,
    track: document.getElementById('wiz-bgm-track').value,
    volume: parseInt(document.getElementById('wiz-bgm-vol').value),
    fade_in: parseFloat(document.getElementById('wiz-bgm-fadein').value),
    fade_out: parseFloat(document.getElementById('wiz-bgm-fadeout').value),
  };
  return audio;
}

function collectWizardSubtitle() {
  return {
    preset: wizardState.selectedSubtitleStyle || 'minimal_white',
    animation: document.getElementById('wiz-sub-anim').value,
    position: document.getElementById('wiz-sub-position').value,
    font_size: parseInt(document.getElementById('wiz-sub-size').value),
    letter_spacing: parseInt(document.getElementById('wiz-sub-letter').value),
    dual_line: document.getElementById('wiz-sub-dual').checked,
    karaoke: document.getElementById('wiz-sub-karaoke').checked,
  };
}

function collectWizardEffects() {
  return {
    transition: document.getElementById('wiz-transition').value,
    filter: document.getElementById('wiz-filter').value,
    filter_intensity: parseInt(document.getElementById('wiz-filter-intensity').value),
    watermark: {
      enabled: document.getElementById('wiz-watermark-enabled').checked,
      text: document.getElementById('wiz-watermark-text').value,
      position: document.getElementById('wiz-watermark-position').value,
      opacity: parseInt(document.getElementById('wiz-watermark-opacity').value),
    },
    intro: {
      enabled: document.getElementById('wiz-intro-enabled').checked,
      text: document.getElementById('wiz-intro-text').value,
      duration: parseInt(document.getElementById('wiz-intro-duration').value) || 3,
    },
    outro: {
      enabled: document.getElementById('wiz-outro-enabled').checked,
      text: document.getElementById('wiz-outro-text').value,
      duration: parseInt(document.getElementById('wiz-outro-duration').value) || 3,
    },
  };
}

// 应用字幕样式预设到颜色配置（写入隐藏状态，保存时由 collectWizardSubtitle 处理）
function applySubtitleStylePreset(key) {
  if (!_creativePresets || !_creativePresets.subtitle_styles[key]) return;
  wizardState.selectedSubtitleStyle = key;
}

async function wizardApplyTemplate() {
  if (!wizardState.selectedTemplate) {
    toast('请先选择一个模板', 'error');
    return;
  }
  const btn = document.getElementById('wizard-apply-template-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 应用中...';
  try {
    const result = await api('/api/templates/apply', {
      method: 'POST',
      body: { template_id: wizardState.selectedTemplate },
    });
    if (result.success) {
      toast(result.message || '模板已应用', 'success');
      // 根据模板填充后续步骤默认值
      const templates = await ensureTemplates();
      const tpl = templates[wizardState.selectedTemplate];
      if (tpl) {
        wizardState.selectedSubtitleStyle = tpl.subtitle_preset;
        if (_creativePresets) {
          setBtnCardValue('wiz-emotion-grid', tpl.emotion);
          const animSel = document.getElementById('wiz-sub-anim');
          if (animSel) animSel.value = tpl.subtitle_animation;
          const transSel = document.getElementById('wiz-transition');
          if (transSel) transSel.value = tpl.transition;
          const filterSel = document.getElementById('wiz-filter');
          if (filterSel) filterSel.value = tpl.filter;
          const bgmSel = document.getElementById('wiz-bgm-track');
          if (bgmSel) bgmSel.value = tpl.bgm_track;
          // 高亮字幕样式卡片
          renderSubtitleStyleGrid('wiz-subtitle-style-grid', _creativePresets.subtitle_styles, tpl.subtitle_preset, (k) => {
            wizardState.selectedSubtitleStyle = k;
          });
          // 启用 BGM
          document.getElementById('wiz-bgm-enabled').checked = true;
          document.getElementById('wiz-bgm-group').style.display = 'block';
        }
      }
    } else {
      toast(result.message || '应用失败', 'error');
    }
  } catch (e) {
    toast(`应用模板失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '✓ 应用此模板';
  }
}

function wizardSkipTemplate() {
  wizardState.selectedTemplate = null;
  toast('已跳过模板，可自定义配置', 'info');
  wizardNext();
}

async function wizardAiGenerate() {
  const topic = document.getElementById('wiz-ai-topic').value.trim();
  const style = document.getElementById('wiz-ai-style').value;
  if (!topic) { toast('请输入创作主题', 'error'); return; }
  const btn = document.getElementById('wiz-ai-generate-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 生成中...';
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script: topic, action: 'generate', style, topic },
    });
    if (result.success) {
      document.getElementById('wiz-script').value = result.script;
      document.getElementById('wiz-script-count').textContent = `${result.char_count} 字`;
      toast(`生成成功${result.mock ? '（Mock 模式）' : ''}`, 'success');
    } else {
      toast(`生成失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`生成失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '💡 生成文案';
  }
}

async function wizardExtractScript() {
  const refUrl = document.getElementById('wiz-ref-url').value.trim();
  if (!refUrl) { toast('请输入参考视频链接', 'error'); return; }
  const btn = document.getElementById('wiz-extract-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 提取中...';
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script: '', action: 'extract', topic: null, style: null, reference_url: refUrl },
    });
    if (result.success) {
      document.getElementById('wiz-script').value = result.script;
      document.getElementById('wiz-script-count').textContent = `${result.char_count} 字`;
      toast('文案提取成功', 'success');
    } else {
      toast(`提取失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`提取失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔗 提取文案';
  }
}

async function wizardScriptProcess() {
  const script = document.getElementById('wiz-script').value.trim();
  const action = wizardState.wizScriptAction;
  const style = action === 'style' ? document.getElementById('wiz-process-style').value : null;
  if (!script) { toast('请先输入文案', 'error'); return; }
  const btn = document.getElementById('wiz-script-process-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> AI 处理中...';
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script, action, style },
    });
    if (result.success) {
      document.getElementById('wiz-script').value = result.script;
      document.getElementById('wiz-script-count').textContent = `${result.char_count} 字`;
      toast(`处理成功${result.mock ? '（Mock 模式）' : ''}`, 'success');
    } else {
      toast(`处理失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`处理失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '▶️ 执行 AI 处理';
  }
}

function renderWizardSummary() {
  const container = document.getElementById('wiz-summary');
  if (!container) return;
  const scene = collectWizardScene();
  const audio = collectWizardAudioWithBgm();
  const subtitle = collectWizardSubtitle();
  const effects = collectWizardEffects();
  const script = document.getElementById('wiz-script').value;
  const avatar = document.getElementById('wiz-avatar').value;
  const voice = document.getElementById('wiz-voice').value;
  const tplLabel = wizardState.selectedTemplate && _templatesCache
    ? (_templatesCache[wizardState.selectedTemplate]?.label || '—') : '未使用';

  container.innerHTML = `
    <div class="summary-card">
      <div class="summary-card-title">📰 模板</div>
      <div class="summary-card-row"><span class="key">模板</span><span class="val">${tplLabel}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title">👤 数字人形象</div>
      <div class="summary-card-row"><span class="key">形象</span><span class="val">${avatar}</span></div>
      <div class="summary-card-row"><span class="key">姿态</span><span class="val">${scene.pose}</span></div>
      <div class="summary-card-row"><span class="key">位置</span><span class="val">${scene.position}</span></div>
      <div class="summary-card-row"><span class="key">大小</span><span class="val">${scene.scale}</span></div>
      <div class="summary-card-row"><span class="key">背景</span><span class="val">${scene.background_type}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title">📝 文案</div>
      <div class="summary-card-row"><span class="key">字数</span><span class="val">${script.length} 字</span></div>
      <div class="summary-card-row"><span class="key">预览</span><span class="val">${script.substring(0, 40)}${script.length > 40 ? '...' : ''}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title">🎙️ 声音</div>
      <div class="summary-card-row"><span class="key">音色</span><span class="val">${voice}</span></div>
      <div class="summary-card-row"><span class="key">语速</span><span class="val">${audio.speed}</span></div>
      <div class="summary-card-row"><span class="key">音量</span><span class="val">${audio.volume}</span></div>
      <div class="summary-card-row"><span class="key">情感</span><span class="val">${audio.emotion}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title">💬 字幕</div>
      <div class="summary-card-row"><span class="key">预设</span><span class="val">${subtitle.preset}</span></div>
      <div class="summary-card-row"><span class="key">动画</span><span class="val">${subtitle.animation}</span></div>
      <div class="summary-card-row"><span class="key">位置</span><span class="val">${subtitle.position}</span></div>
      <div class="summary-card-row"><span class="key">双行</span><span class="val">${subtitle.dual_line ? '是' : '否'}</span></div>
      <div class="summary-card-row"><span class="key">卡拉OK</span><span class="val">${subtitle.karaoke ? '是' : '否'}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title">🎵 BGM</div>
      <div class="summary-card-row"><span class="key">启用</span><span class="val">${audio.bgm.enabled ? '是' : '否'}</span></div>
      <div class="summary-card-row"><span class="key">曲目</span><span class="val">${audio.bgm.track}</span></div>
      <div class="summary-card-row"><span class="key">音量</span><span class="val">${audio.bgm.volume}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title">🎬 效果</div>
      <div class="summary-card-row"><span class="key">转场</span><span class="val">${effects.transition}</span></div>
      <div class="summary-card-row"><span class="key">滤镜</span><span class="val">${effects.filter}</span></div>
      <div class="summary-card-row"><span class="key">水印</span><span class="val">${effects.watermark.enabled ? '是' : '否'}</span></div>
    </div>
  `;
}

async function wizardGenerate() {
  const script = document.getElementById('wiz-script').value.trim();
  const refUrl = document.getElementById('wiz-ref-url').value.trim();
  if (!script && !refUrl) {
    toast('请先在步骤3输入文案', 'error');
    wizardGoToStep(3);
    return;
  }
  const avatar = document.getElementById('wiz-avatar').value;
  const voice = document.getElementById('wiz-voice').value;
  const platform = document.getElementById('wiz-platform').value;
  const autoPublish = document.getElementById('wiz-auto-publish').checked;

  const btn = document.getElementById('wiz-generate-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 生成中...';

  // 渲染初始进度
  const wizPipeline = document.getElementById('wiz-pipeline');
  if (wizPipeline) wizPipeline.innerHTML = STEP_ORDER.map(step => {
    const info = STEP_INFO[step];
    return `<div class="pipeline-step pending"><div class="step-icon">○</div><div class="step-info"><div class="step-name">${info.icon} ${info.name}</div><div class="step-status">等待中</div></div></div>`;
  }).join('');

  try {
    // 先保存所有配置
    await Promise.all([
      api('/api/settings/scene', { method: 'PUT', body: { section: 'scene', data: collectWizardScene() } }).catch(() => {}),
      api('/api/settings/audio', { method: 'PUT', body: { section: 'audio', data: collectWizardAudioWithBgm() } }).catch(() => {}),
      api('/api/settings/subtitle', { method: 'PUT', body: { section: 'subtitle', data: collectWizardSubtitle() } }).catch(() => {}),
      api('/api/settings/effects', { method: 'PUT', body: { section: 'effects', data: collectWizardEffects() } }).catch(() => {}),
    ]);

    const result = await api('/api/generate', {
      method: 'POST',
      body: {
        script, reference_video_url: refUrl || null,
        avatar_id: avatar, voice_id: voice,
        script_mode: 'polish', platform, auto_publish: autoPublish,
      },
    });

    // 更新进度
    const stepsState = {};
    if (result.steps) {
      for (const [name, info] of Object.entries(result.steps)) {
        stepsState[name] = info.status;
      }
    }
    if (wizPipeline) {
      wizPipeline.innerHTML = STEP_ORDER.map(step => {
        const info = STEP_INFO[step];
        const status = stepsState[step] || 'pending';
        const icons = { pending: '○', running: '⟳', success: '✓', failed: '✕', skipped: '−' };
        const statusText = { pending: '等待中', running: '执行中...', success: '已完成', failed: '失败', skipped: '已跳过' };
        return `<div class="pipeline-step ${status}"><div class="step-icon">${icons[status] || '○'}</div><div class="step-info"><div class="step-name">${info.icon} ${info.name}</div><div class="step-status">${statusText[status] || status}</div></div></div>`;
      }).join('');
    }

    // 展示结果
    const output = result.output || {};
    const videoPath = output.final_video;
    const title = output.title || '';
    const scriptText = output.script_text || '';
    const videoEl = document.getElementById('wiz-result-video');
    if (videoPath) {
      videoEl.innerHTML = `<video src="/api/files?path=${encodeURIComponent(videoPath)}" controls autoplay></video>`;
    } else {
      videoEl.innerHTML = '<div class="result-video-placeholder">视频未生成</div>';
    }
    document.getElementById('wiz-result-title').textContent = title || '—';
    document.getElementById('wiz-result-script').textContent = scriptText || '—';

    toast(result.success ? '视频生成成功！' : '生成未完全成功', result.success ? 'success' : 'error');
  } catch (e) {
    toast(`生成失败: ${e.message}`, 'error');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🚀 开始生成视频';
  }
}

// ========== 模板中心页面 ==========

async function loadTemplatesCenter() {
  try {
    const templates = await ensureTemplates();
    const grid = document.getElementById('templates-grid');
    if (!grid) return;
    grid.innerHTML = Object.entries(templates).map(([key, tpl]) => `
      <div class="template-card" data-key="${key}">
        <div class="template-card-icon">${tpl.icon}</div>
        <div class="template-card-label">${tpl.label}</div>
        <div class="template-card-desc">${tpl.description}</div>
        <div class="template-card-tags">
          <span class="template-card-tag">${tpl.subtitle_preset}</span>
          <span class="template-card-tag">${tpl.emotion}</span>
          <span class="template-card-tag">${tpl.filter}</span>
          <span class="template-card-tag">${tpl.transition}</span>
        </div>
        <div class="template-card-actions">
          <button class="btn btn-primary btn-sm btn-block" onclick="applyTemplateFromCenter('${key}')">应用模板</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    toast(`加载模板失败: ${e.message}`, 'error');
  }
}

async function applyTemplateFromCenter(templateId) {
  try {
    const result = await api('/api/templates/apply', {
      method: 'POST',
      body: { template_id: templateId },
    });
    toast(result.success ? (result.message || '模板应用成功') : (result.message || '应用失败'),
          result.success ? 'success' : 'error');
  } catch (e) {
    toast(`应用模板失败: ${e.message}`, 'error');
  }
}

// ========== 一键生成页面 ==========

const STEP_INFO = {
  script_extract: { name: '文案提取', icon: '📝' },
  script_write: { name: '文案仿写', icon: '✍️' },
  tts: { name: '语音合成', icon: '🎙️' },
  avatar: { name: '数字人生成', icon: '👤' },
  subtitle: { name: '字幕生成', icon: '💬' },
  compose: { name: '视频合成', icon: '🎬' },
  title: { name: '标题生成', icon: '📌' },
  cover: { name: '封面生成', icon: '🖼️' },
  publish: { name: '多平台发布', icon: '📤' },
};

const STEP_ORDER = ['script_extract', 'script_write', 'tts', 'avatar', 'subtitle', 'compose', 'title', 'cover', 'publish'];

function renderPipeline(stepsState = {}) {
  const container = document.getElementById('pipeline');
  container.innerHTML = STEP_ORDER.map(step => {
    const info = STEP_INFO[step];
    const status = stepsState[step] || 'pending';
    const icons = {
      pending: '○', running: '⟳', success: '✓', failed: '✕', skipped: '−',
    };
    const statusText = {
      pending: '等待中', running: '执行中...', success: '已完成', failed: '失败', skipped: '已跳过',
    };
    return `
      <div class="pipeline-step ${status}">
        <div class="step-icon">${icons[status] || '○'}</div>
        <div class="step-info">
          <div class="step-name">${info.icon} ${info.name}</div>
          <div class="step-status">${statusText[status] || status}</div>
        </div>
      </div>
    `;
  }).join('');
}

async function loadAvatarsForSelect() {
  try {
    const avatars = await api('/api/avatars');
    const select = document.getElementById('gen-avatar');
    const ids = avatars.length ? avatars.map(a => a.avatar_id) : ['default'];
    select.innerHTML = ids.map(id => `<option value="${id}">${id}</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

async function loadVoicesForSelect() {
  try {
    const voices = await api('/api/voices');
    const select = document.getElementById('gen-voice');
    const ids = voices.length ? voices.map(v => v.voice_id) : ['default'];
    select.innerHTML = ids.map(id => `<option value="${id}">${id}</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

async function handleGenerate() {
  const script = document.getElementById('gen-script').value.trim();
  const refUrl = document.getElementById('gen-ref-url').value.trim();
  const avatar = document.getElementById('gen-avatar').value;
  const voice = document.getElementById('gen-voice').value;
  const mode = document.getElementById('gen-mode').value;
  const platform = document.getElementById('gen-platform').value;
  const autoPublish = document.getElementById('gen-publish').checked;

  if (!script && !refUrl) {
    toast('请输入文案或参考视频链接', 'error');
    return;
  }

  const btn = document.getElementById('gen-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 生成中...';

  // 初始进度展示
  renderPipeline({});

  try {
    const result = await api('/api/generate', {
      method: 'POST',
      body: {
        script, reference_video_url: refUrl || null,
        avatar_id: avatar, voice_id: voice,
        script_mode: mode, platform, auto_publish: autoPublish,
      },
    });

    // 从 steps 构建进度状态
    const stepsState = {};
    if (result.steps) {
      for (const [name, info] of Object.entries(result.steps)) {
        stepsState[name] = info.status;
      }
    }
    renderPipeline(stepsState);

    // 展示结果
    const output = result.output || {};
    const videoPath = output.final_video;
    const title = output.title || '';
    const coverPath = output.cover;
    const scriptText = output.script_text || '';

    // 视频
    const videoEl = document.getElementById('result-video');
    if (videoPath) {
      videoEl.innerHTML = `<video src="/api/files?path=${encodeURIComponent(videoPath)}" controls autoplay></video>`;
    } else {
      videoEl.innerHTML = '<div class="result-video-placeholder">视频未生成</div>';
    }

    // 标题
    document.getElementById('result-title').textContent = title || '—';

    // 封面
    const coverEl = document.getElementById('result-cover');
    if (coverPath) {
      coverEl.innerHTML = `<img class="meta-image" src="/api/files?path=${encodeURIComponent(coverPath)}" alt="封面">`;
    } else {
      coverEl.innerHTML = '<span class="meta-value">—</span>';
    }

    // 文案
    document.getElementById('result-script').textContent = scriptText || '—';

    // 详情
    document.getElementById('result-detail').textContent = JSON.stringify(result, null, 2);

    toast(result.success ? '视频生成成功！' : '生成未完全成功', result.success ? 'success' : 'error');
  } catch (e) {
    toast(`生成失败: ${e.message}`, 'error');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🚀 开始生成视频';
  }
}

// ========== 分步创作页面 ==========

async function loadAvatarsForSelect2() {
  try {
    const avatars = await api('/api/avatars');
    const select = document.getElementById('step-avatar');
    const ids = avatars.length ? avatars.map(a => a.avatar_id) : ['default'];
    select.innerHTML = ids.map(id => `<option value="${id}">${id}</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

async function loadVoicesForSelect2() {
  try {
    const voices = await api('/api/voices');
    const select = document.getElementById('step-voice');
    const ids = voices.length ? voices.map(v => v.voice_id) : ['default'];
    select.innerHTML = ids.map(id => `<option value="${id}">${id}</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

async function handleRunModule() {
  const script = document.getElementById('step-script').value.trim();
  const refUrl = document.getElementById('step-ref-url').value.trim();
  const avatar = document.getElementById('step-avatar').value;
  const voice = document.getElementById('step-voice').value;
  const mode = document.getElementById('step-mode').value;
  const platform = document.getElementById('step-platform').value;
  const moduleName = document.getElementById('step-module').value;

  if (!script && !refUrl) {
    toast('请输入文案或参考视频链接', 'error');
    return;
  }

  const btn = document.getElementById('step-run-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 执行中...';

  try {
    const result = await api('/api/module/run', {
      method: 'POST',
      body: {
        module_name: moduleName, script,
        reference_video_url: refUrl || null,
        avatar_id: avatar, voice_id: voice,
        script_mode: mode, platform,
      },
    });

    document.getElementById('step-result').textContent = JSON.stringify(result, null, 2);

    // 展示音频/视频产物
    const ctx = result.context || {};
    const audioEl = document.getElementById('step-audio');
    const videoEl = document.getElementById('step-video');

    if (ctx.audio_path) {
      audioEl.innerHTML = `<audio src="/api/files?path=${encodeURIComponent(ctx.audio_path)}" controls style="width:100%"></audio>`;
    } else {
      audioEl.innerHTML = '<span style="color:var(--text-muted)">无音频产物</span>';
    }

    const videoPath = ctx.raw_video_path || ctx.final_video;
    if (videoPath) {
      videoEl.innerHTML = `<video src="/api/files?path=${encodeURIComponent(videoPath)}" controls style="width:100%;border-radius:10px"></video>`;
    } else {
      videoEl.innerHTML = '<span style="color:var(--text-muted)">无视频产物</span>';
    }

    toast(result.success ? `模块 ${moduleName} 执行成功` : `模块 ${moduleName} 执行失败`, result.success ? 'success' : 'error');
  } catch (e) {
    toast(`执行失败: ${e.message}`, 'error');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '▶️ 执行此模块';
  }
}

// ========== 任务管理页面 ==========

async function loadJobs() {
  try {
    const jobs = await api('/api/jobs?limit=50');
    const tbody = document.getElementById('jobs-tbody');
    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:40px;color:var(--text-muted)">暂无任务</td></tr>';
      return;
    }
    tbody.innerHTML = jobs.map(j => `
      <tr>
        <td style="font-family:var(--font-mono);font-size:12px">${j.job_id}</td>
        <td>${statusBadge(j.status)}</td>
        <td>${formatTime(j.created_at)}</td>
        <td>${formatTime(j.updated_at)}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="showJobDetail('${j.job_id}')">详情</button>
          <button class="btn btn-sm btn-secondary" onclick="rerunJob('${j.job_id}')">续跑</button>
          <button class="btn btn-sm btn-danger" onclick="deleteJob('${j.job_id}')">删除</button>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    toast(`加载任务失败: ${e.message}`, 'error');
  }
}

async function showJobDetail(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    const detail = document.getElementById('job-detail');
    const stepsHtml = (job.steps || []).map(s => `
      <div class="pipeline-step ${s.status}">
        <div class="step-icon">${STEP_INFO[s.step]?.icon || '○'}</div>
        <div class="step-info">
          <div class="step-name">${STEP_INFO[s.step]?.name || s.step}</div>
          <div class="step-status">${s.status} ${s.duration ? `· ${s.duration.toFixed(2)}s` : ''}</div>
        </div>
      </div>
    `).join('');
    detail.innerHTML = `
      <div style="margin-bottom:16px">
        <strong>任务 ID:</strong> ${job.job_id}<br>
        <strong>状态:</strong> ${statusBadge(job.status)}<br>
        <strong>创建时间:</strong> ${formatTime(job.created_at)}
      </div>
      <div class="pipeline">${stepsHtml}</div>
      ${job.error ? `<div style="margin-top:12px;color:var(--color-error)">错误: ${job.error}</div>` : ''}
    `;
  } catch (e) {
    toast(`加载详情失败: ${e.message}`, 'error');
  }
}

async function rerunJob(jobId) {
  if (!confirm(`确定要续跑任务 ${jobId} 吗？`)) return;
  try {
    toast('正在续跑任务...', 'info');
    const result = await api(`/api/jobs/${jobId}/rerun`, { method: 'POST' });
    toast(result.success ? '续跑成功' : '续跑失败', result.success ? 'success' : 'error');
    loadJobs();
  } catch (e) {
    toast(`续跑失败: ${e.message}`, 'error');
  }
}

async function deleteJob(jobId) {
  if (!confirm(`确定要删除任务 ${jobId} 吗？此操作不可撤销。`)) return;
  try {
    await api(`/api/jobs/${jobId}`, { method: 'DELETE' });
    toast('任务已删除', 'success');
    loadJobs();
  } catch (e) {
    toast(`删除失败: ${e.message}`, 'error');
  }
}

// ========== 形象管理页面 ==========

async function loadAvatars() {
  try {
    const avatars = await api('/api/avatars');
    const grid = document.getElementById('avatars-grid');
    if (!avatars.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👤</div><div>暂无已注册形象</div></div>';
      return;
    }
    grid.innerHTML = avatars.map(a => `
      <div class="asset-card">
        <div class="asset-id">${a.avatar_id}</div>
        <div class="asset-meta">${a.meta?.mode || 'mock'} 模式</div>
      </div>
    `).join('');
  } catch (e) {
    toast(`加载形象失败: ${e.message}`, 'error');
  }
}

async function handleRegisterAvatar() {
  const avatarId = document.getElementById('avatar-id').value.trim();
  const fileInput = document.getElementById('avatar-file');
  if (!avatarId) { toast('请输入形象 ID', 'error'); return; }
  if (!fileInput.files.length) { toast('请选择参考视频', 'error'); return; }

  const formData = new FormData();
  formData.append('avatar_id', avatarId);
  formData.append('file', fileInput.files[0]);

  const btn = document.getElementById('avatar-reg-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 注册中...';

  try {
    const resp = await fetch('/api/avatars/register', { method: 'POST', body: formData });
    const result = await resp.json();
    toast(result.success ? '形象注册成功' : '注册失败', result.success ? 'success' : 'error');
    if (result.success) {
      document.getElementById('avatar-id').value = '';
      fileInput.value = '';
      loadAvatars();
    }
  } catch (e) {
    toast(`注册失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📥 注册形象';
  }
}

// ========== 音色管理页面 ==========

async function loadVoices() {
  try {
    const voices = await api('/api/voices');
    const grid = document.getElementById('voices-grid');
    if (!voices.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎙️</div><div>暂无已注册音色</div></div>';
      return;
    }
    grid.innerHTML = voices.map(v => `
      <div class="asset-card">
        <div class="asset-id">${v.voice_id}</div>
        <div class="asset-meta">已注册</div>
      </div>
    `).join('');
  } catch (e) {
    toast(`加载音色失败: ${e.message}`, 'error');
  }
}

async function handleRegisterVoice() {
  const voiceId = document.getElementById('voice-id').value.trim();
  const fileInput = document.getElementById('voice-file');
  if (!voiceId) { toast('请输入音色 ID', 'error'); return; }
  if (!fileInput.files.length) { toast('请选择样本音频', 'error'); return; }

  const formData = new FormData();
  formData.append('voice_id', voiceId);
  formData.append('file', fileInput.files[0]);

  const btn = document.getElementById('voice-reg-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 注册中...';

  try {
    const resp = await fetch('/api/voices/register', { method: 'POST', body: formData });
    const result = await resp.json();
    toast(result.success ? '音色注册成功' : '注册失败', result.success ? 'success' : 'error');
    if (result.success) {
      document.getElementById('voice-id').value = '';
      fileInput.value = '';
      loadVoices();
    }
  } catch (e) {
    toast(`注册失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📥 注册音色';
  }
}

// ========== 系统状态页面 ==========

async function loadHealth() {
  try {
    const health = await api('/api/health');
    const container = document.getElementById('health-content');
    const items = [
      { key: 'ffmpeg', label: 'FFmpeg 视频处理', icon: '🎬' },
      { key: 'gpu_tts', label: '云端 TTS 服务', icon: '🎙️' },
      { key: 'gpu_avatar', label: '云端数字人服务', icon: '👤' },
      { key: 'llm_mock', label: 'LLM 模式', icon: '🧠' },
      { key: 'avatars_count', label: '已注册形象', icon: '👥' },
      { key: 'voices_count', label: '已注册音色', icon: '🎵' },
    ];
    container.innerHTML = items.map(item => {
      const val = health[item.key];
      let display;
      if (typeof val === 'boolean') {
        display = val
          ? '<span class="badge badge-success">可用</span>'
          : '<span class="badge badge-error">不可用</span>';
      } else if (item.key === 'llm_mock') {
        display = val
          ? '<span class="badge badge-warning">Mock 模式</span>'
          : '<span class="badge badge-success">真实 API</span>';
      } else {
        display = `<span class="badge badge-info">${val}</span>`;
      }
      return `
        <div class="card" style="display:flex;align-items:center;justify-content:space-between">
          <div style="display:flex;align-items:center;gap:14px">
            <span style="font-size:24px">${item.icon}</span>
            <span style="font-weight:600">${item.label}</span>
          </div>
          ${display}
        </div>
      `;
    }).join('');

    // 更新侧边栏状态
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (health.ffmpeg) {
      dot.classList.remove('offline');
      text.textContent = '系统正常';
    } else {
      dot.classList.add('offline');
      text.textContent = '系统异常';
    }
  } catch (e) {
    toast(`健康检查失败: ${e.message}`, 'error');
  }
}

// ========== 文案工作台页面 ==========

let currentScriptAction = 'polish';

async function loadAvatarsForSelect3() {
  try {
    const avatars = await api('/api/avatars');
    const select = document.getElementById('batch-avatar');
    if (!select) return;
    const ids = avatars.length ? avatars.map(a => a.avatar_id) : ['default'];
    select.innerHTML = ids.map(id => `<option value="${id}">${id}</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

async function loadVoicesForSelect3() {
  try {
    const voices = await api('/api/voices');
    const select = document.getElementById('batch-voice');
    if (!select) return;
    const ids = voices.length ? voices.map(v => v.voice_id) : ['default'];
    select.innerHTML = ids.map(id => `<option value="${id}">${id}</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

function selectScriptAction(action) {
  currentScriptAction = action;
  document.querySelectorAll('.action-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.action === action);
  });
  // 显示/隐藏附加输入
  document.getElementById('topic-input-group').style.display = action === 'generate' ? 'block' : 'none';
  document.getElementById('style-input-group').style.display = action === 'style' ? 'block' : 'none';
}

async function handleScriptProcess() {
  const script = document.getElementById('script-input').value.trim();
  const topic = document.getElementById('script-topic').value.trim();
  const style = document.getElementById('script-style').value;
  const action = currentScriptAction;

  if (action !== 'generate' && !script) {
    toast('请输入文案', 'error');
    return;
  }
  if (action === 'generate' && !topic && !script) {
    toast('请输入创作主题', 'error');
    return;
  }

  const btn = document.getElementById('script-process-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> AI 处理中...';

  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script, action, style: action === 'style' ? style : null, topic: action === 'generate' ? topic : null },
    });

    if (result.success) {
      document.getElementById('script-output').value = result.script;
      document.getElementById('script-output-count').textContent = `${result.char_count} 字`;
      toast(`处理成功${result.mock ? '（Mock 模式）' : ''}`, 'success');
    } else {
      toast(`处理失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`处理失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '▶️ 执行 AI 处理';
  }
}

function handleScriptCopy() {
  const output = document.getElementById('script-output');
  if (!output.value) {
    toast('暂无内容可复制', 'error');
    return;
  }
  output.select();
  document.execCommand('copy');
  toast('已复制到剪贴板', 'success');
}

function handleScriptToGenerate() {
  const output = document.getElementById('script-output').value;
  if (!output) {
    toast('暂无文案，请先处理', 'error');
    return;
  }
  document.getElementById('gen-script').value = output;
  navigate('generate');
  toast('已填入文案，可点击「开始生成视频」', 'info');
}

function handleScriptClear() {
  document.getElementById('script-input').value = '';
  document.getElementById('script-output').value = '';
  document.getElementById('script-topic').value = '';
  document.getElementById('script-char-count').textContent = '0 字';
  document.getElementById('script-output-count').textContent = '0 字';
}

// ========== 批量处理页面 ==========

async function handleBatchGenerate() {
  const scriptsText = document.getElementById('batch-scripts').value.trim();
  if (!scriptsText) {
    toast('请输入文案', 'error');
    return;
  }

  // 按空行分割
  const scripts = scriptsText.split(/\n\s*\n/).map(s => s.trim()).filter(s => s);
  if (scripts.length === 0) {
    toast('未识别到有效文案', 'error');
    return;
  }

  const avatar = document.getElementById('batch-avatar').value;
  const voice = document.getElementById('batch-voice').value;
  const mode = document.getElementById('batch-mode').value;
  const platform = document.getElementById('batch-platform').value;

  const btn = document.getElementById('batch-run-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 批量生成中...';

  // 初始化进度列表
  const listEl = document.getElementById('batch-progress-list');
  const badgeEl = document.getElementById('batch-progress-badge');
  badgeEl.textContent = `0 / ${scripts.length}`;
  listEl.innerHTML = scripts.map((s, i) => `
    <div class="batch-item" id="batch-item-${i}">
      <div class="batch-item-index">${i + 1}</div>
      <div class="batch-item-content">
        <div class="batch-item-text">${s.substring(0, 60)}${s.length > 60 ? '...' : ''}</div>
        <div class="batch-item-meta">等待中...</div>
      </div>
    </div>
  `).join('');

  try {
    const items = scripts.map(s => ({
      script: s, avatar_id: avatar, voice_id: voice,
      script_mode: mode, platform, auto_publish: false,
    }));

    // 逐条提交并更新进度
    let completed = 0;
    for (let i = 0; i < items.length; i++) {
      const itemEl = document.getElementById(`batch-item-${i}`);
      itemEl.classList.add('running');
      itemEl.querySelector('.batch-item-meta').textContent = '生成中...';

      try {
        const result = await api('/api/generate', { method: 'POST', body: items[i] });
        completed++;
        badgeEl.textContent = `${completed} / ${scripts.length}`;
        if (result.success) {
          itemEl.classList.remove('running');
          itemEl.classList.add('success');
          const videoPath = result.output?.final_video || '';
          itemEl.querySelector('.batch-item-meta').innerHTML = `✅ 成功 · ${videoPath ? `<a href="/api/files?path=${encodeURIComponent(videoPath)}" target="_blank">查看视频</a>` : ''}`;
        } else {
          itemEl.classList.remove('running');
          itemEl.classList.add('failed');
          itemEl.querySelector('.batch-item-meta').textContent = `❌ 失败: ${result.error || '未知错误'}`;
        }
      } catch (e) {
        itemEl.classList.remove('running');
        itemEl.classList.add('failed');
        itemEl.querySelector('.batch-item-meta').textContent = `❌ 异常: ${e.message}`;
      }
    }

    const successCount = document.querySelectorAll('.batch-item.success').length;
    toast(`批量完成：${successCount}/${scripts.length} 成功`, successCount === scripts.length ? 'success' : 'info');
  } catch (e) {
    toast(`批量处理失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📦 开始批量生成';
  }
}

// ========== 初始化 ==========

document.addEventListener('DOMContentLoaded', () => {
  // 导航绑定
  PAGES.forEach(p => {
    const nav = document.getElementById(`nav-${p}`);
    if (nav) nav.addEventListener('click', () => navigate(p));
  });

  // 按钮绑定
  document.getElementById('gen-btn').addEventListener('click', handleGenerate);
  document.getElementById('step-run-btn').addEventListener('click', handleRunModule);
  document.getElementById('avatar-reg-btn').addEventListener('click', handleRegisterAvatar);
  document.getElementById('voice-reg-btn').addEventListener('click', handleRegisterVoice);
  document.getElementById('refresh-jobs-btn').addEventListener('click', loadJobs);
  document.getElementById('refresh-health-btn').addEventListener('click', loadHealth);

  // 文案工作台
  document.querySelectorAll('.action-btn').forEach(btn => {
    btn.addEventListener('click', () => selectScriptAction(btn.dataset.action));
  });
  document.getElementById('script-process-btn').addEventListener('click', handleScriptProcess);
  document.getElementById('script-copy-btn').addEventListener('click', handleScriptCopy);
  document.getElementById('script-to-generate-btn').addEventListener('click', handleScriptToGenerate);
  document.getElementById('script-clear-btn').addEventListener('click', handleScriptClear);
  document.getElementById('script-input').addEventListener('input', e => {
    document.getElementById('script-char-count').textContent = `${e.target.value.length} 字`;
  });

  // 批量处理
  document.getElementById('batch-run-btn').addEventListener('click', handleBatchGenerate);

  // 模板中心刷新
  document.getElementById('refresh-templates-btn')?.addEventListener('click', () => {
    _templatesCache = null;
    loadTemplatesCenter();
  });

  // 初始渲染进度
  renderPipeline({});

  // 加载首页数据（默认创作向导）
  navigate('wizard');
  loadHealth();
});
