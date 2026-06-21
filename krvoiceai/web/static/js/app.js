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
  'dashboard', 'wizard', 'generate', 'script', 'step-by-step', 'batch', 'timeline',
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

  // 更新底部导航栏激活状态（移动端）
  document.querySelectorAll('.bottom-nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.page === page);
  });

  // 移动端：导航后自动关闭侧边栏抽屉
  closeSidebarDrawer();

  // 滚动到顶部（移动端 body 滚动 / 桌面端 main-content 滚动）
  const mainContent = document.querySelector('.main-content');
  if (mainContent) mainContent.scrollTop = 0;
  window.scrollTo(0, 0);

  // 页面加载时刷新数据
  if (page === 'dashboard') loadDashboard();
  if (page === 'jobs') loadJobs();
  if (page === 'avatars') loadAvatars();
  if (page === 'voices') loadVoices();
  if (page === 'health') loadHealth();
  if (page === 'wizard') initWizard();
  if (page === 'templates') { loadTemplatesCenter(); loadSceneTemplates(); loadPresetAvatars(); loadPresetVoices(); }
  if (page === 'generate') { loadAvatarsForSelect(); loadVoicesForSelect(); }
  if (page === 'step-by-step') { loadAvatarsForSelect2(); loadVoicesForSelect2(); }
  if (page === 'batch') { loadAvatarsForSelect3(); loadVoicesForSelect3(); }
  if (page === 'timeline') initTimelineEditor();
  if (page === 'settings-models') loadAllSettings();
  if (page === 'settings-video') loadVideoSettings();
  if (page === 'settings-scene') loadSceneEffectSettings();
  if (page === 'settings-publish') loadPublishSettings();
}

// ========== 移动端侧边栏抽屉 ==========

function openSidebarDrawer() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  const toggle = document.getElementById('menu-toggle');
  if (sidebar) sidebar.classList.add('open');
  if (overlay) overlay.classList.add('active');
  if (toggle) toggle.classList.add('active');
}

function closeSidebarDrawer() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  const toggle = document.getElementById('menu-toggle');
  if (sidebar) sidebar.classList.remove('open');
  if (overlay) overlay.classList.remove('active');
  if (toggle) toggle.classList.remove('active');
}

// ========== 首页仪表盘 ==========

async function loadDashboard() {
  loadDashboardJobs();
  loadDashboardTemplates();
  loadDashboardStatus();
}

async function loadDashboardJobs() {
  const container = document.getElementById('dash-recent-list');
  if (!container) return;
  try {
    const jobs = await api('/api/jobs?limit=8');
    if (!jobs || !jobs.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎬</div><div>还没有创作记录，点击上方按钮开始吧</div></div>';
      return;
    }
    // 并行获取每个 job 的详情以拿到标题/封面
    const detailPromises = jobs.slice(0, 8).map(j =>
      api(`/api/jobs/${j.job_id}`).catch(() => null)
    );
    const details = await Promise.all(detailPromises);
    container.innerHTML = jobs.slice(0, 8).map((j, i) => {
      const detail = details[i] || {};
      const output = detail.output || {};
      const input = detail.input || {};
      const title = output.title || input.script?.substring(0, 20) || j.job_id;
      const coverPath = output.cover;
      const coverHtml = coverPath
        ? `<img src="/api/files?path=${encodeURIComponent(coverPath)}" alt="封面" onerror="this.parentElement.innerHTML='🎬'">`
        : '🎬';
      return `
        <div class="recent-card" onclick="showJobDetail('${j.job_id}');navigate('jobs')">
          <div class="recent-card-thumb">${coverHtml}</div>
          <div class="recent-card-body">
            <div class="recent-card-title">${escapeHtml(title)}</div>
            <div class="recent-card-meta">
              ${statusBadge(j.status)}
              <span class="recent-card-time">${formatTime(j.created_at)}</span>
            </div>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎬</div><div>加载失败，请稍后重试</div></div>';
  }
}

async function loadDashboardTemplates() {
  const grid = document.getElementById('dash-template-grid');
  if (!grid) return;
  try {
    const templates = await ensureTemplates();
    const entries = Object.entries(templates).slice(0, 6);
    grid.innerHTML = entries.map(([key, tpl]) => `
      <div class="template-card" data-key="${key}">
        <div class="template-card-icon">${tpl.icon}</div>
        <div class="template-card-label">${tpl.label}</div>
        <div class="template-card-desc">${tpl.description}</div>
        <div class="template-card-tags">
          <span class="template-card-tag">${tpl.subtitle_preset}</span>
          <span class="template-card-tag">${tpl.emotion}</span>
        </div>
      </div>
    `).join('');
    grid.querySelectorAll('.template-card').forEach(card => {
      card.addEventListener('click', () => applyDashboardTemplate(card.dataset.key));
    });
  } catch (e) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎨</div><div>模板加载失败</div></div>';
  }
}

async function applyDashboardTemplate(templateId) {
  try {
    const result = await api('/api/templates/apply', {
      method: 'POST',
      body: { template_id: templateId },
    });
    if (result.success) {
      toast(result.message || '模板已应用，即将进入创作向导', 'success');
      navigate('wizard');
    } else {
      toast(result.message || '应用失败', 'error');
    }
  } catch (e) {
    toast(`应用模板失败: ${e.message}`, 'error');
  }
}

async function loadDashboardStatus() {
  const bar = document.getElementById('dash-status-bar');
  if (!bar) return;
  try {
    const health = await api('/api/health');
    const items = bar.querySelectorAll('.status-bar-item');
    items.forEach(item => {
      const key = item.dataset.key;
      item.classList.remove('ok', 'warn', 'error');
      let ok = false, warn = false;
      if (key === 'ffmpeg') ok = !!health.ffmpeg;
      else if (key === 'llm') ok = !health.llm_mock;
      else if (key === 'tts') ok = !!health.gpu_tts;
      else if (key === 'avatar') ok = !!health.gpu_avatar;
      if (ok) item.classList.add('ok');
      else item.classList.add('warn');
    });
  } catch (e) {
    /* 忽略 */
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
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

// 渲染字幕样式预设网格（可视化预览）
function renderSubtitleStyleGrid(gridId, presets, selectedKey, onSelect) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.innerHTML = Object.entries(presets).map(([key, info]) => {
    const color = assToHex(info.primary_color);
    const outline = assToHex(info.outline_color);
    const stroke = info.outline_width || 2;
    const shadow = info.shadow_color ? assToHex(info.shadow_color) : 'transparent';
    return `
      <div class="subtitle-style-card ${key === selectedKey ? 'active' : ''}" data-key="${key}">
        <div class="subtitle-style-preview" style="color:${color};text-shadow:-${stroke}px -${stroke}px 0 ${outline},${stroke}px -${stroke}px 0 ${outline},-${stroke}px ${stroke}px 0 ${outline},${stroke}px ${stroke}px 0 ${outline},2px 2px 4px ${shadow}">示例字幕效果</div>
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
  sceneCategory: null,  // 从首页场景卡带入的分类
};

// 场景分类 → 推荐默认配置（对标旗博士/万兴播爆"选场景即配好参数"）
const SCENE_CATEGORY_DEFAULTS = {
  self_media: {
    label: '自媒体口播',
    subtitle_preset: 'douyin_hot',
    subtitle_animation: 'bounce',
    bgm_track: 'vlog_chill',
    emotion: 'cheerful',
    filter: 'vlog',
    transition: 'slideleft',
    speech_speed: 1.0,
  },
  marketing: {
    label: '营销推广',
    subtitle_preset: 'pop_pink',
    subtitle_animation: 'bounce',
    bgm_track: 'upbeat_corporate',
    emotion: 'excited',
    filter: 'vivid',
    transition: 'zoom',
    speech_speed: 1.1,
  },
  knowledge: {
    label: '知识科普',
    subtitle_preset: 'tech_blue',
    subtitle_animation: 'fade',
    bgm_track: 'ambient_calm',
    emotion: 'neutral',
    filter: 'none',
    transition: 'fade',
    speech_speed: 0.95,
  },
  enterprise: {
    label: '政企宣传',
    subtitle_preset: 'classic_gold',
    subtitle_animation: 'fade',
    bgm_track: 'upbeat_corporate',
    emotion: 'neutral',
    filter: 'cinematic',
    transition: 'fade',
    speech_speed: 0.95,
  },
};

function initWizard() {
  if (!wizardState.initialized) {
    wizardState.initialized = true;
    loadWizardData();
  }
  // 若从首页场景卡进入，应用对应分类的推荐默认值
  if (wizardState.sceneCategory) {
    applySceneCategoryDefaults(wizardState.sceneCategory);
  }
  // 若从场景模板进入，预填文案
  if (wizardState.sceneScript) {
    setTimeout(() => {
      const wizScript = document.getElementById('wiz-script');
      if (wizScript) {
        wizScript.value = wizardState.sceneScript;
        updateScriptStats(wizardState.sceneScript);
      }
    }, 500);
  }
}

// 应用场景分类推荐默认配置到向导表单（对标万兴播爆"选场景即配好参数"）
function applySceneCategoryDefaults(scene) {
  const defaults = SCENE_CATEGORY_DEFAULTS[scene];
  if (!defaults) return;
  try {
    // 字幕样式
    wizardState.selectedSubtitleStyle = defaults.subtitle_preset;
    const subAnim = document.getElementById('wiz-sub-anim');
    if (subAnim) subAnim.value = defaults.subtitle_animation;
    // 滤镜/转场
    const filterSel = document.getElementById('wiz-filter');
    if (filterSel) filterSel.value = defaults.filter;
    const transSel = document.getElementById('wiz-transition');
    if (transSel) transSel.value = defaults.transition;
    // 语速
    const speed = document.getElementById('wiz-speed');
    if (speed) speed.value = defaults.speech_speed;
    // BGM
    const bgmEnabled = document.getElementById('wiz-bgm-enabled');
    const bgmTrack = document.getElementById('wiz-bgm-track');
    if (bgmEnabled) bgmEnabled.checked = true;
    if (bgmTrack) bgmTrack.value = defaults.bgm_track;
    const bgmGroup = document.getElementById('wiz-bgm-group');
    if (bgmGroup) bgmGroup.style.display = 'block';
    // 情感（btn-card-grid）
    setBtnCardValue('wiz-emotion-grid', defaults.emotion);
    toast(`已应用「${defaults.label}」推荐配置：字幕/${defaults.subtitle_preset} · 滤镜/${defaults.filter} · 转场/${defaults.transition}`, 'success');
  } catch (e) {
    console.warn('应用场景默认配置失败:', e.message);
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

    // 形象/音色卡片网格
    renderWizardAvatarGrid(avatars);
    renderWizardVoiceGrid(voices);

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

    // 文案字数统计 + 时长预估 + 警告
    document.getElementById('wiz-script').addEventListener('input', e => {
      updateScriptStats(e.target.value);
    });

    // 文案 AI 工具栏
    bindScriptToolbar();

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

// 渲染数字人卡片网格
function renderWizardAvatarGrid(avatars) {
  const grid = document.getElementById('wiz-avatar-grid');
  if (!grid) return;
  const list = avatars && avatars.length ? avatars : [{ avatar_id: 'default', reference_image: null }];
  grid.innerHTML = list.map(a => {
    const id = a.avatar_id;
    const mode = a.meta?.mode || 'mock';
    const hasLipSync = a.meta?.has_lip_sync || mode === 'wav2lip';
    const lipBadge = hasLipSync
      ? '<span style="position:absolute;top:4px;right:4px;background:#10b981;color:#fff;font-size:9px;padding:1px 4px;border-radius:3px">👄 唇形</span>'
      : '';
    const imgHtml = `<img src="/api/avatars/${encodeURIComponent(id)}/preview" alt="${id}" onerror="this.parentElement.innerHTML='👤'">`;
    return `
      <div class="avatar-card" data-id="${id}" style="position:relative">
        <div class="avatar-card-img">${imgHtml}${lipBadge}</div>
        <div class="avatar-card-id">${id}</div>
      </div>
    `;
  }).join('');
  // 默认选中第一个
  const firstId = list[0].avatar_id;
  document.getElementById('wiz-avatar').value = firstId;
  grid.querySelectorAll('.avatar-card').forEach(card => {
    if (card.dataset.id === firstId) card.classList.add('selected');
    card.addEventListener('click', () => {
      const isSelected = card.classList.contains('selected');
      grid.querySelectorAll('.avatar-card').forEach(c => c.classList.remove('selected'));
      if (isSelected) {
        // 再次点击取消，但仍保留一个默认值
        document.getElementById('wiz-avatar').value = firstId;
      } else {
        card.classList.add('selected');
        document.getElementById('wiz-avatar').value = card.dataset.id;
      }
    });
  });
}

// 渲染音色卡片网格
function renderWizardVoiceGrid(voices) {
  const grid = document.getElementById('wiz-voice-grid');
  if (!grid) return;
  const list = voices && voices.length ? voices : [{ voice_id: 'default', type: 'provider_default', provider: 'mock' }];
  grid.innerHTML = list.map(v => {
    const id = v.voice_id;
    const type = v.type || 'custom';
    const provider = v.provider || 'mock';
    const typeLabel = type === 'provider_default' || type === 'default' ? '默认' : '自定义';
    const typeClass = type === 'provider_default' || type === 'default' ? 'type-default' : 'type-custom';
    return `
      <div class="voice-card" data-id="${id}">
        <div class="voice-card-header">
          <div class="voice-card-info">
            <div class="voice-card-name">${id}</div>
            <div class="voice-card-tags">
              <span class="voice-card-tag ${typeClass}">${typeLabel}</span>
              <span class="voice-card-tag provider">${provider}</span>
            </div>
          </div>
          <button class="voice-preview-btn" data-voice="${id}" type="button" title="试听">▶️</button>
        </div>
      </div>
    `;
  }).join('');
  // 默认选中第一个
  const firstId = list[0].voice_id;
  document.getElementById('wiz-voice').value = firstId;
  grid.querySelectorAll('.voice-card').forEach(card => {
    if (card.dataset.id === firstId) card.classList.add('selected');
    card.addEventListener('click', e => {
      // 点击试听按钮不触发选中
      if (e.target.closest('.voice-preview-btn')) return;
      const isSelected = card.classList.contains('selected');
      grid.querySelectorAll('.voice-card').forEach(c => c.classList.remove('selected'));
      if (isSelected) {
        document.getElementById('wiz-voice').value = firstId;
      } else {
        card.classList.add('selected');
        document.getElementById('wiz-voice').value = card.dataset.id;
      }
    });
  });
  // 试听按钮
  grid.querySelectorAll('.voice-preview-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      playVoicePreview(btn.dataset.voice, btn);
    });
  });
}

// 试听音色
let _currentPreviewAudio = null;
let _currentPreviewBtn = null;

async function playVoicePreview(voiceId, btn) {
  // 如果正在播放，停止
  if (_currentPreviewAudio && !_currentPreviewAudio.paused) {
    _currentPreviewAudio.pause();
    if (_currentPreviewBtn) {
      _currentPreviewBtn.classList.remove('playing');
      _currentPreviewBtn.textContent = '▶️';
    }
    // 如果点的是同一个按钮，仅停止
    if (_currentPreviewBtn === btn) {
      _currentPreviewAudio = null;
      _currentPreviewBtn = null;
      return;
    }
  }
  btn.classList.add('playing');
  btn.textContent = '⏸️';
  _currentPreviewBtn = btn;
  try {
    // 调用 module/run 执行 TTS 合成短句
    const result = await api('/api/module/run', {
      method: 'POST',
      body: {
        module_name: 'tts',
        script: '你好，这是音色试听',
        avatar_id: document.getElementById('wiz-avatar').value || 'default',
        voice_id: voiceId,
        script_mode: 'polish',
        platform: 'douyin',
      },
    });
    const ctx = result.context || {};
    const audioPath = ctx.audio_path;
    if (!audioPath) {
      throw new Error('未返回音频文件');
    }
    const audio = new Audio(`/api/files?path=${encodeURIComponent(audioPath)}`);
    _currentPreviewAudio = audio;
    audio.addEventListener('ended', () => {
      btn.classList.remove('playing');
      btn.textContent = '▶️';
      _currentPreviewAudio = null;
      _currentPreviewBtn = null;
    });
    audio.addEventListener('error', () => {
      btn.classList.remove('playing');
      btn.textContent = '▶️';
      _currentPreviewAudio = null;
      _currentPreviewBtn = null;
      toast('音频播放失败', 'error');
    });
    await audio.play();
  } catch (e) {
    btn.classList.remove('playing');
    btn.textContent = '▶️';
    _currentPreviewAudio = null;
    _currentPreviewBtn = null;
    toast(`试听失败: ${e.message}`, 'error');
  }
}

// 文案字数统计 + 时长预估 + 警告
function updateScriptStats(text) {
  const len = text.length;
  const duration = Math.ceil(len / 4); // 每秒4字
  const countEl = document.getElementById('wiz-script-count');
  if (countEl) countEl.textContent = `${len} 字`;
  const statsEl = document.getElementById('wiz-script-stats');
  if (statsEl) {
    statsEl.querySelector('.script-stats-count').textContent = `字数 ${len} 字`;
    statsEl.querySelector('.script-stats-duration').textContent = `预估时长 ${duration} 秒`;
  }
  const warningEl = document.getElementById('wiz-script-warning');
  if (warningEl) {
    if (len > 500) {
      warningEl.style.display = 'block';
      warningEl.textContent = '⚠️ 文案较长，生成时间可能增加';
    } else {
      warningEl.style.display = 'none';
    }
  }
}

// 绑定文案 AI 工具栏
function bindScriptToolbar() {
  const polishBtn = document.getElementById('wiz-polish-btn');
  const polishMenu = document.getElementById('wiz-polish-menu');
  if (polishBtn && polishMenu) {
    polishBtn.addEventListener('click', e => {
      e.stopPropagation();
      polishMenu.classList.toggle('open');
    });
    polishMenu.querySelectorAll('.script-dropdown-item').forEach(item => {
      item.addEventListener('click', () => {
        polishMenu.classList.remove('open');
        wizardScriptQuickProcess('polish', item.dataset.style);
      });
    });
    document.addEventListener('click', () => polishMenu.classList.remove('open'));
  }
  const expandBtn = document.getElementById('wiz-expand-btn');
  if (expandBtn) expandBtn.addEventListener('click', () => wizardScriptQuickProcess('expand', null));
  const shortenBtn = document.getElementById('wiz-shorten-btn');
  if (shortenBtn) shortenBtn.addEventListener('click', () => wizardScriptQuickProcess('shorten', null));
  const clearBtn = document.getElementById('wiz-clear-btn');
  if (clearBtn) clearBtn.addEventListener('click', () => {
    document.getElementById('wiz-script').value = '';
    updateScriptStats('');
    toast('已清空文案', 'info');
  });
}

// 文案快速 AI 处理（工具栏）
async function wizardScriptQuickProcess(action, style) {
  const script = document.getElementById('wiz-script').value.trim();
  if (!script) { toast('请先输入文案', 'error'); return; }
  toast(`正在执行 AI ${action === 'polish' ? '润色' : action === 'expand' ? '扩写' : '缩写'}...`, 'info');
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script, action, style },
    });
    if (result.success) {
      document.getElementById('wiz-script').value = result.script;
      updateScriptStats(result.script);
      toast(`处理成功${result.mock ? '（Mock 模式）' : ''}`, 'success');
    } else {
      toast(`处理失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`处理失败: ${e.message}`, 'error');
  }
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
      updateScriptStats(result.script);
      // AI 生成成功后切换到"手动输入"标签页，让用户看到生成的文案
      switchWizardScriptTab('manual');
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
      updateScriptStats(result.script);
      // 提取成功后自动切换到"手动输入"标签页，让用户看到提取的文案
      switchWizardScriptTab('manual');
      const mockHint = result.mock ? '（Mock 模式：未配置 ASR，返回示例文案。配置 MiMo ASR 可提取真实文案）' : '';
      toast(`文案提取成功${mockHint}`, 'success');
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

// 切换 wizard 步骤3 的子标签页（manual/ai/extract）
function switchWizardScriptTab(tabName) {
  document.querySelectorAll('[data-wiztab]').forEach(t => {
    t.classList.toggle('active', t.dataset.wiztab === tabName);
  });
  document.querySelectorAll('.sub-page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(`wiz-script-${tabName}`);
  if (target) target.classList.add('active');
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
      updateScriptStats(result.script);
      // AI 处理成功后切换到"手动输入"标签页，让用户看到处理结果
      switchWizardScriptTab('manual');
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

  // 渲染初始进度（向导页内）
  const wizPipeline = document.getElementById('wiz-pipeline');
  if (wizPipeline) wizPipeline.innerHTML = STEP_ORDER.map(step => {
    const info = STEP_INFO[step];
    return `<div class="pipeline-step pending"><div class="step-icon">○</div><div class="step-info"><div class="step-name">${info.icon} ${info.name}</div><div class="step-status">等待中</div></div></div>`;
  }).join('');

  // 显示进度模态框
  showProgressModal();

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

    // 更新模态框进度
    updateProgressModal(stepsState, result);

    // 展示结果（向导页内）
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
    // 友好化错误提示
    let errMsg = e.message || '未知错误';
    if (errMsg.includes('Gateway') || errMsg.includes('502') || errMsg.includes('503') || errMsg.includes('504')) {
      errMsg = 'AI 服务暂时不可用（网关错误），请稍后重试。可能是 LLM/TTS API 限流或服务端临时故障。';
    } else if (errMsg.includes('timeout') || errMsg.includes('Timeout')) {
      errMsg = '请求超时，请检查网络或稍后重试。';
    } else if (errMsg.includes('Failed to fetch') || errMsg.includes('NetworkError')) {
      errMsg = '网络连接失败，请检查服务器是否运行。';
    }
    toast(`生成失败: ${errMsg}`, 'error');
    console.error(e);
    // 模态框显示错误
    finishProgressModalError(errMsg);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🚀 开始生成视频';
  }
}

// ========== 进度模态框 ==========

let _progressStartTime = 0;

function showProgressModal() {
  const modal = document.getElementById('progress-modal');
  if (!modal) return;
  _progressStartTime = Date.now();
  modal.style.display = 'flex';
  document.getElementById('progress-modal-title').textContent = '正在生成视频...';
  document.getElementById('progress-modal-close').style.display = 'none';
  document.getElementById('progress-modal-result').style.display = 'none';
  document.getElementById('progress-bar-fill').style.width = '0%';
  document.getElementById('progress-percent').textContent = '0%';
  document.getElementById('progress-eta').textContent = '预估剩余时间 计算中...';
  // 渲染 9 个阶段
  const stagesEl = document.getElementById('progress-stages');
  stagesEl.innerHTML = STEP_ORDER.map(step => {
    const info = STEP_INFO[step];
    return `
      <div class="progress-stage pending" data-step="${step}">
        <div class="progress-stage-icon">○</div>
        <div class="progress-stage-name">${info.icon} ${info.name}</div>
        <div class="progress-stage-status">等待中</div>
      </div>
    `;
  }).join('');
}

function updateProgressModal(stepsState, result) {
  const stagesEl = document.getElementById('progress-stages');
  if (!stagesEl) return;
  const icons = { pending: '○', running: '⟳', success: '✓', failed: '✕', skipped: '−' };
  const statusText = { pending: '等待中', running: '执行中', success: '已完成', failed: '失败', skipped: '已跳过' };
  let completed = 0;
  let failed = 0;
  stagesEl.querySelectorAll('.progress-stage').forEach(stage => {
    const step = stage.dataset.step;
    const status = stepsState[step] || 'pending';
    stage.className = `progress-stage ${status}`;
    stage.querySelector('.progress-stage-icon').textContent = icons[status] || '○';
    stage.querySelector('.progress-stage-status').textContent = statusText[status] || status;
    if (status === 'success' || status === 'skipped') completed++;
    if (status === 'failed') failed++;
  });
  // 进度百分比
  const percent = Math.round((completed / STEP_ORDER.length) * 100);
  document.getElementById('progress-bar-fill').style.width = percent + '%';
  document.getElementById('progress-percent').textContent = percent + '%';
  // 预估剩余时间
  const elapsed = (Date.now() - _progressStartTime) / 1000;
  if (completed > 0 && completed < STEP_ORDER.length) {
    const avgPerStep = elapsed / completed;
    const remaining = Math.round(avgPerStep * (STEP_ORDER.length - completed));
    document.getElementById('progress-eta').textContent = `预估剩余时间 ${remaining} 秒`;
  } else if (completed >= STEP_ORDER.length) {
    document.getElementById('progress-eta').textContent = `已完成 · 用时 ${elapsed.toFixed(1)} 秒`;
  }
  // 完成或失败时显示结果
  if (result && (result.success || failed > 0 || completed >= STEP_ORDER.length)) {
    finishProgressModal(result, failed > 0);
  }
}

function finishProgressModal(result, hasFailed) {
  document.getElementById('progress-modal-title').textContent = hasFailed ? '生成未完全成功' : '视频生成成功！';
  document.getElementById('progress-modal-close').style.display = 'flex';
  const resultEl = document.getElementById('progress-modal-result');
  const output = result.output || {};
  const videoPath = output.final_video;
  const title = output.title || '';
  if (videoPath) {
    resultEl.innerHTML = `
      <div class="progress-modal-result-title">${escapeHtml(title)}</div>
      <video src="/api/files?path=${encodeURIComponent(videoPath)}" controls autoplay></video>
      <div class="progress-modal-result-actions">
        <a class="btn btn-primary" href="/api/files?path=${encodeURIComponent(videoPath)}" target="_blank" download>⬇️ 下载视频</a>
        <button class="btn btn-secondary" type="button" onclick="closeProgressModal()">🔄 再做一个</button>
      </div>
    `;
  } else {
    resultEl.innerHTML = `
      <div class="progress-modal-result-title">视频未生成</div>
      <div class="progress-modal-result-actions">
        <button class="btn btn-secondary" type="button" onclick="closeProgressModal()">🔄 再做一个</button>
      </div>
    `;
  }
  resultEl.style.display = 'block';
}

function finishProgressModalError(message) {
  document.getElementById('progress-modal-title').textContent = '生成失败';
  document.getElementById('progress-modal-close').style.display = 'flex';
  const resultEl = document.getElementById('progress-modal-result');
  resultEl.innerHTML = `
    <div class="progress-modal-result-title" style="color:var(--color-error)">❌ ${escapeHtml(message)}</div>
    <div class="progress-modal-result-actions">
      <button class="btn btn-secondary" type="button" onclick="closeProgressModal()">关闭</button>
    </div>
  `;
  resultEl.style.display = 'block';
}

function closeProgressModal() {
  const modal = document.getElementById('progress-modal');
  if (modal) modal.style.display = 'none';
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
    if (result.success) {
      toast(result.message || '模板应用成功，即将进入创作向导', 'success');
      // 自动跳转到创作向导（对标万兴播爆"选模板→自动进入创作"）
      wizardState.selectedTemplate = templateId;
      navigate('wizard');
    } else {
      toast(result.message || '应用失败', 'error');
    }
  } catch (e) {
    toast(`应用模板失败: ${e.message}`, 'error');
  }
}

// ========== 场景化模板中心（对标腾讯智影/万兴播爆） ==========

const sceneState = {
  templates: {},        // 场景模板列表
  currentTemplate: null, // 当前选中的模板详情
  placeholders: {},     // 占位符输入值
};

// 加载场景模板列表
async function loadSceneTemplates() {
  try {
    const resp = await fetch('/api/scene/templates');
    const data = await resp.json();
    sceneState.templates = data.templates || {};
    const grid = document.getElementById('scene-templates-grid');
    if (!grid) return;
    if (Object.keys(sceneState.templates).length === 0) {
      grid.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">暂无场景模板</div>';
      return;
    }
    grid.innerHTML = Object.entries(sceneState.templates).map(([tid, tpl]) => {
      const styleTags = [];
      if (tpl.style) {
        if (tpl.style.subtitle_preset) styleTags.push(`字幕:${tpl.style.subtitle_preset}`);
        if (tpl.style.bgm_track) styleTags.push(`BGM:${tpl.style.bgm_track}`);
        if (tpl.style.filter && tpl.style.filter !== 'none') styleTags.push(`滤镜:${tpl.style.filter}`);
        if (tpl.style.transition && tpl.style.transition !== 'none') styleTags.push(`转场:${tpl.style.transition}`);
        if (tpl.style.emotion) styleTags.push(`情感:${tpl.style.emotion}`);
      }
      return `
        <div class="scene-template-card" onclick="openSceneModal('${tid}')">
          <div class="scene-icon">${tpl.icon || '📋'}</div>
          <div class="scene-label">${tpl.label}</div>
          <div class="scene-category">${tpl.category || '其他'}</div>
          <div class="scene-desc">${tpl.description || ''}</div>
          <div class="scene-style-tags">
            ${styleTags.map(t => `<span class="scene-style-tag">${t}</span>`).join('')}
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    toast(`加载场景模板失败: ${e.message}`, 'error');
  }
}

// 打开场景模板弹窗（加载详情+占位符输入）
async function openSceneModal(templateId) {
  try {
    const resp = await fetch(`/api/scene/templates/${templateId}`);
    const data = await resp.json();
    if (!data.success) {
      toast(data.error || '加载模板失败', 'error');
      return;
    }
    sceneState.currentTemplate = data.template;
    sceneState.currentTemplate.id = templateId;
    sceneState.placeholders = {};
    const tpl = data.template;
    document.getElementById('scene-modal-title').textContent = `${tpl.icon || '📋'} ${tpl.label} - 场景创作`;
    // 渲染占位符输入表单
    const body = document.getElementById('scene-modal-body');
    const placeholders = tpl.placeholders || {};
    let html = `
      <div style="margin-bottom:16px;padding:12px;background:rgba(16,185,129,0.08);border-left:3px solid #10b981;border-radius:4px;font-size:12px;color:var(--text-secondary);line-height:1.5">
        <strong>📝 文案骨架：</strong>填入下方关键词，系统将自动生成完整口播文案。每个字段都有示例提示，照着填即可。
      </div>
    `;
    Object.entries(placeholders).forEach(([key, hint]) => {
      html += `
        <div class="placeholder-input-group">
          <label>${key} <span class="placeholder-hint">· ${hint}</span></label>
          <input type="text" id="ph-${key}" placeholder="${hint}" oninput="sceneState.placeholders['${key}']=this.value">
        </div>
      `;
    });
    html += `<div id="scene-script-preview" style="display:none"><div style="font-size:12px;font-weight:600;margin-top:12px;margin-bottom:6px">📄 生成文案预览</div><div class="scene-preview-script" id="scene-preview-content"></div></div>`;
    body.innerHTML = html;
    document.getElementById('scene-modal').style.display = '';
  } catch (e) {
    toast(`打开模板失败: ${e.message}`, 'error');
  }
}

function closeSceneModal() {
  document.getElementById('scene-modal').style.display = 'none';
  sceneState.currentTemplate = null;
  sceneState.placeholders = {};
}

// 生成文案（填充占位符）
async function generateSceneScript() {
  if (!sceneState.currentTemplate) return;
  const tid = sceneState.currentTemplate.id;
  const values = { ...sceneState.placeholders };
  // 也从 DOM 读取（防止 oninput 未触发）
  Object.keys(sceneState.currentTemplate.placeholders || {}).forEach(key => {
    const el = document.getElementById(`ph-${key}`);
    if (el && el.value) values[key] = el.value;
  });
  const unfilled = Object.keys(sceneState.currentTemplate.placeholders || {}).filter(k => !values[k]);
  if (unfilled.length > 0) {
    toast(`请填写: ${unfilled.join(', ')}`, 'error');
    return;
  }
  try {
    const btn = document.getElementById('scene-generate-btn');
    btn.disabled = true;
    btn.textContent = '生成中...';
    const resp = await fetch('/api/scene/fill-script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: tid, values }),
    });
    const data = await resp.json();
    if (data.success) {
      document.getElementById('scene-script-preview').style.display = '';
      document.getElementById('scene-preview-content').textContent = data.script;
      // 存储生成的文案供后续使用
      sceneState.generatedScript = data.script;
      toast('文案生成成功！可复制使用或一键应用样式后去生成视频', 'success');
    } else {
      toast(data.error || '生成失败', 'error');
    }
  } catch (e) {
    toast(`生成失败: ${e.message}`, 'error');
  } finally {
    const btn = document.getElementById('scene-generate-btn');
    btn.disabled = false;
    btn.textContent = '生成文案';
  }
}

// 一键应用场景样式（字幕/BGM/滤镜/转场/情感/语速）
async function applySceneStyle() {
  if (!sceneState.currentTemplate) return;
  const tid = sceneState.currentTemplate.id;
  try {
    const btn = document.getElementById('scene-apply-style-btn');
    btn.disabled = true;
    btn.textContent = '应用中...';
    const resp = await fetch('/api/scene/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: tid }),
    });
    const data = await resp.json();
    if (data.success) {
      toast(`样式应用成功！已设置: ${data.applied_sections.join(', ')}`, 'success');
      // 关闭弹窗，自动跳转到创作向导并预填文案（对标万兴播爆"一键创作"无缝流程）
      closeSceneModal();
      wizardState.sceneScript = sceneState.generatedScript || '';
      navigate('wizard');
      // 向导加载后预填文案到步骤3
      setTimeout(() => {
        const wizScript = document.getElementById('wiz-script');
        if (wizScript && sceneState.generatedScript) {
          wizScript.value = sceneState.generatedScript;
          updateScriptStats(sceneState.generatedScript);
          // 自动跳到步骤3（文案输入）
          wizardGoToStep(3);
          toast('已自动填入场景文案，可直接进入下一步', 'success');
        }
      }, 800);
    } else {
      toast(data.error || '应用失败', 'error');
    }
  } catch (e) {
    toast(`应用失败: ${e.message}`, 'error');
  } finally {
    const btn = document.getElementById('scene-apply-style-btn');
    btn.disabled = false;
    btn.textContent = '一键应用样式';
  }
}

// 加载预制形象库
async function loadPresetAvatars() {
  try {
    const resp = await fetch('/api/presets/avatars');
    const data = await resp.json();
    const grid = document.getElementById('preset-avatars-grid');
    if (!grid) return;
    const avatars = data.avatars || {};
    if (Object.keys(avatars).length === 0) {
      grid.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">暂无预制形象</div>';
      return;
    }
    grid.innerHTML = Object.entries(avatars).map(([aid, info]) => {
      const scenes = (info.recommended_scenes || []).slice(0, 3).join('、');
      return `
        <div class="preset-avatar-card">
          <img src="/api/presets/avatars/${aid}/image" alt="${info.label}" onerror="this.style.display='none';this.nextElementSibling.style.display=''">
          <div class="preset-avatar-icon" style="display:none">${info.icon || '👤'}</div>
          <div class="preset-avatar-name">${info.label}</div>
          <div class="preset-avatar-desc">${info.description || ''}</div>
          <div class="preset-avatar-scenes">适合: ${scenes}</div>
          <button class="btn btn-sm btn-primary btn-block" onclick="usePresetAvatar('${aid}', '${info.recommended_voice || ''}', '${info.recommended_emotion || ''}')">使用此形象</button>
        </div>
      `;
    }).join('');
  } catch (e) {
    toast(`加载预制形象失败: ${e.message}`, 'error');
  }
}

// 使用预制形象（注册形象+设置推荐音色+情感，并跳转向导预选）
async function usePresetAvatar(avatarId, voice, emotion) {
  try {
    // 1. 注册预制形象为用户形象（对标万兴播爆"一键使用模板形象"）
    let targetAvatarId = 'default';
    const regResp = await fetch(`/api/presets/avatars/${encodeURIComponent(avatarId)}/register`, { method: 'POST' });
    const regData = await regResp.json();
    if (regData.success) {
      targetAvatarId = regData.avatar_id;
    }

    // 2. 设置推荐音色
    if (voice) {
      const resp = await fetch('/api/settings/tts', { method: 'PUT' });
      const ttsSection = await resp.json();
      const ttsData = ttsSection.data || {};
      ttsData.default_voice = voice;
      if (emotion) ttsData.emotion = emotion;
      await fetch('/api/settings/tts', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ttsData),
      });
    }

    // 3. 跳转到创作向导并预选该形象
    wizardState.presetAvatarId = targetAvatarId;
    navigate('wizard');
    // 向导数据加载后刷新形象列表并预选
    setTimeout(async () => {
      try {
        const avatars = await api('/api/avatars').catch(() => []);
        if (avatars && avatars.length) {
          renderWizardAvatarGrid(avatars);
        }
        const avatarInput = document.getElementById('wiz-avatar');
        if (avatarInput && targetAvatarId !== 'default') {
          avatarInput.value = targetAvatarId;
          document.querySelectorAll('#wiz-avatar-grid .avatar-card').forEach(c => {
            c.classList.toggle('selected', c.dataset.id === targetAvatarId);
          });
        }
      } catch (e) { /* 忽略刷新失败 */ }
    }, 600);

    toast(`已使用该形象${voice ? '（音色: ' + voice + (emotion ? ' / 情感: ' + emotion : '') + '）' : ''}，即将进入创作向导`, 'success');
  } catch (e) {
    toast(`设置失败: ${e.message}`, 'error');
  }
}

// 加载预制音色库
async function loadPresetVoices() {
  try {
    const resp = await fetch('/api/presets/voices');
    const data = await resp.json();
    const grid = document.getElementById('preset-voices-grid');
    if (!grid) return;
    const voices = data.voices || {};
    if (Object.keys(voices).length === 0) {
      grid.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">暂无预制音色</div>';
      return;
    }
    grid.innerHTML = Object.entries(voices).map(([vid, info]) => {
      const scenes = (info.recommended_scenes || []).slice(0, 3).join('、');
      return `
        <div class="preset-voice-card">
          <div class="preset-voice-icon">${info.gender === 'female' ? '👩' : '👨'}</div>
          <div class="preset-voice-name">${info.label}</div>
          <div class="preset-voice-desc">${info.description || ''}</div>
          <div class="preset-voice-scenes">适合: ${scenes}</div>
          <button class="btn btn-sm btn-primary btn-block" onclick="usePresetVoice('${vid}')">使用此音色</button>
        </div>
      `;
    }).join('');
  } catch (e) {
    toast(`加载预制音色失败: ${e.message}`, 'error');
  }
}

// 使用预制音色
async function usePresetVoice(voiceId) {
  try {
    // 先确保 TTS provider 是 edge_tts
    const getResp = await fetch('/api/settings/tts');
    const ttsSection = await getResp.json();
    const ttsData = ttsSection.data || {};
    ttsData.provider = 'edge_tts';
    ttsData.default_voice = voiceId;
    const resp = await fetch('/api/settings/tts', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ttsData),
    });
    const result = await resp.json();
    toast(result.success ? `已切换到 Edge TTS 并设置音色: ${voiceId}` : '设置失败', result.success ? 'success' : 'error');
  } catch (e) {
    toast(`设置失败: ${e.message}`, 'error');
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

// 上传文件选择时预览
function onAvatarFileSelected(input) {
  const file = input.files[0];
  const textEl = document.getElementById('avatar-upload-text');
  const previewEl = document.getElementById('avatar-preview');
  if (!file) {
    textEl.textContent = '点击或拖拽上传照片/视频';
    previewEl.style.display = 'none';
    previewEl.innerHTML = '';
    return;
  }
  textEl.textContent = file.name;
  previewEl.style.display = 'block';
  previewEl.innerHTML = '';
  // 图片直接预览，视频抽帧预览
  if (file.type.startsWith('image/')) {
    const url = URL.createObjectURL(file);
    previewEl.innerHTML = `<img src="${url}" style="max-width:100%;max-height:200px;border-radius:8px;border:1px solid #e0e0e0">`;
  } else if (file.type.startsWith('video/')) {
    const url = URL.createObjectURL(file);
    previewEl.innerHTML = `<video src="${url}" controls style="max-width:100%;max-height:200px;border-radius:8px;border:1px solid #e0e0e0"></video>`;
  }
}

async function loadAvatars() {
  try {
    const avatars = await api('/api/avatars');
    const grid = document.getElementById('avatars-grid');
    if (!avatars.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👤</div><div>暂无已注册形象</div><div style="font-size:12px;color:#999;margin-top:6px">请上传真人照片/视频注册</div></div>';
      return;
    }
    grid.innerHTML = avatars.map(a => {
      const mode = a.meta?.mode || 'mock';
      const hasLipSync = a.meta?.has_lip_sync || mode === 'wav2lip';
      const refType = a.meta?.reference_type || (a.reference_image ? 'photo' : 'unknown');
      const lipBadge = hasLipSync
        ? '<span style="color:#10b981;font-size:11px">👄 唇形同步</span>'
        : '<span style="color:#999;font-size:11px">静态图</span>';
      const modeBadge = `<span style="color:#6b7280;font-size:11px">${mode}</span>`;
      // 参考图预览
      let imgHtml = '<div style="width:100%;height:120px;background:#f5f5f5;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#bbb">无预览</div>';
      if (a.reference_image || hasLipSync || mode !== 'mock') {
        imgHtml = `<img src="/api/avatars/${encodeURIComponent(a.avatar_id)}/preview" style="width:100%;height:120px;object-fit:cover;border-radius:6px" onerror="this.outerHTML='<div style=&quot;width:100%;height:120px;background:#f5f5f5;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#bbb&quot;>无预览</div>'">`;
      }
      return `
        <div class="asset-card" style="padding:10px">
          ${imgHtml}
          <div class="asset-id" style="margin-top:8px">${a.avatar_id}</div>
          <div style="display:flex;gap:8px;margin-top:4px">${lipBadge} ${modeBadge}</div>
          ${refType === 'video' ? '<div style="font-size:11px;color:#6b7280;margin-top:2px">📹 视频参考</div>' : ''}
        </div>
      `;
    }).join('');
  } catch (e) {
    toast(`加载形象失败: ${e.message}`, 'error');
  }
}

async function handleRegisterAvatar() {
  const avatarId = document.getElementById('avatar-id').value.trim();
  const fileInput = document.getElementById('avatar-file');
  if (!avatarId) { toast('请输入形象 ID', 'error'); return; }
  if (!fileInput.files.length) { toast('请选择参考照片或视频', 'error'); return; }

  const file = fileInput.files[0];
  const isImage = file.type.startsWith('image/');
  const isVideo = file.type.startsWith('video/');
  if (!isImage && !isVideo) { toast('请上传图片或视频文件', 'error'); return; }

  const formData = new FormData();
  formData.append('avatar_id', avatarId);
  formData.append('file', file);

  const btn = document.getElementById('avatar-reg-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 注册中...';

  try {
    const resp = await fetch('/api/avatars/register', { method: 'POST', body: formData });
    const result = await resp.json();
    if (result.success) {
      toast(`形象注册成功！${isImage ? '照片' : '视频'}已保存，将用于 Wav2Lip 唇形同步`, 'success');
      document.getElementById('avatar-id').value = '';
      fileInput.value = '';
      document.getElementById('avatar-upload-text').textContent = '点击或拖拽上传照片/视频';
      document.getElementById('avatar-preview').style.display = 'none';
      document.getElementById('avatar-preview').innerHTML = '';
      loadAvatars();
    } else {
      toast('注册失败', 'error');
    }
  } catch (e) {
    toast(`注册失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📥 注册形象（Wav2Lip 唇形同步）';
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

  // 移动端：汉堡菜单切换侧边栏抽屉
  document.getElementById('menu-toggle')?.addEventListener('click', () => {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar?.classList.contains('open')) {
      closeSidebarDrawer();
    } else {
      openSidebarDrawer();
    }
  });
  // 移动端：点击遮罩关闭抽屉
  document.getElementById('sidebar-overlay')?.addEventListener('click', closeSidebarDrawer);
  // 移动端：快速创建按钮
  document.getElementById('mobile-quick-create')?.addEventListener('click', () => navigate('wizard'));
  // 移动端：底部导航栏
  document.querySelectorAll('.bottom-nav-item').forEach(item => {
    item.addEventListener('click', () => navigate(item.dataset.page));
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
  document.getElementById('refresh-scene-templates-btn')?.addEventListener('click', loadSceneTemplates);
  document.getElementById('refresh-preset-avatars-btn')?.addEventListener('click', loadPresetAvatars);
  document.getElementById('refresh-preset-voices-btn')?.addEventListener('click', loadPresetVoices);

  // 首页仪表盘按钮
  document.getElementById('dash-new-video-btn')?.addEventListener('click', () => navigate('wizard'));
  document.getElementById('dash-from-template-btn')?.addEventListener('click', () => navigate('templates'));
  document.getElementById('dash-view-all-jobs')?.addEventListener('click', () => navigate('jobs'));
  document.getElementById('dash-view-all-templates')?.addEventListener('click', () => navigate('templates'));
  // 场景卡点击跳转到创作向导，并带入场景分类上下文
  document.querySelectorAll('.scene-card').forEach(card => {
    card.addEventListener('click', () => {
      const scene = card.dataset.scene;
      wizardState.sceneCategory = scene;
      navigate('wizard');
      // 应用该场景分类的推荐默认配置
      applySceneCategoryDefaults(scene);
    });
  });

  // 进度模态框关闭
  document.getElementById('progress-modal-close')?.addEventListener('click', closeProgressModal);

  // 初始渲染进度
  renderPipeline({});

  // 加载首页数据（默认首页仪表盘）
  navigate('dashboard');
  loadHealth();
});

// ========== 时间轴剪辑编辑器（画中画/B-roll） ==========

// 时间轴编辑器状态
const tlState = {
  jobs: [],              // 任务列表
  currentJob: null,      // 当前选中的任务
  videoPath: '',         // 当前视频路径
  videoDuration: 0,      // 视频时长
  subtitleSegments: [],  // 字幕片段 [{text, start, end}]
  brollAssets: [],       // B-roll 素材库
  selectedAsset: null,   // 当前选中的素材
  clips: [],             // 已添加的 B-roll 片段
  pendingClip: null,     // 正在编辑的片段（弹窗中）
  editingClipIdx: -1,    // 正在编辑的已有片段索引（-1 表示新增）
  timelineWidth: 800,    // 时间轴像素宽度
  pxPerSec: 20,          // 每秒像素数
  quickEditAction: '',   // 当前快捷剪辑操作
};

// 初始化时间轴编辑器
async function initTimelineEditor() {
  await Promise.all([loadTimelineJobs(), loadBrollAssets()]);
}

// 加载有视频的任务列表
async function loadTimelineJobs() {
  try {
    const jobs = await api('/api/jobs?limit=50');
    const select = document.getElementById('tl-job-select');
    // 筛选有视频产物的任务
    const videoJobs = [];
    for (const job of jobs) {
      const detail = await api(`/api/jobs/${job.job_id}`);
      const output = detail.output || {};
      const steps = detail.steps || [];
      // 检查是否有 avatar 或 compose 步骤成功
      const hasVideo = steps.some(s =>
        (s.step === 'avatar' || s.step === 'compose') &&
        s.status === 'success' && s.result
      );
      if (hasVideo) {
        const videoPath = output.final_video || output.raw_video ||
          (steps.find(s => s.step === 'avatar')?.result?.video_path) || '';
        videoJobs.push({
          job_id: job.job_id,
          status: job.status,
          created_at: job.created_at,
          video_path: videoPath,
          output,
          steps,
        });
      }
    }
    tlState.jobs = videoJobs;
    select.innerHTML = '<option value="">-- 选择任务 --</option>' +
      videoJobs.map(j => {
        const date = new Date(j.created_at * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
        return `<option value="${j.job_id}">${date} - ${j.job_id}</option>`;
      }).join('');
  } catch (e) {
    toast(`加载任务失败: ${e.message}`, 'error');
  }
}

// 选中任务后加载视频和字幕
async function onTimelineJobSelected() {
  const jobId = document.getElementById('tl-job-select').value;
  if (!jobId) {
    document.getElementById('tl-editor-empty').style.display = '';
    document.getElementById('tl-editor').style.display = 'none';
    return;
  }
  const job = tlState.jobs.find(j => j.job_id === jobId);
  if (!job) return;
  tlState.currentJob = job;

  // 获取视频路径
  let videoPath = job.video_path;
  if (!videoPath) {
    toast('该任务无视频产物', 'error');
    return;
  }
  tlState.videoPath = videoPath;

  // 显示编辑器
  document.getElementById('tl-editor-empty').style.display = 'none';
  document.getElementById('tl-editor').style.display = '';

  // 加载视频预览
  const videoEl = document.getElementById('tl-video-preview');
  videoEl.src = `/api/files?path=${encodeURIComponent(videoPath)}`;
  videoEl.onloadedmetadata = () => {
    tlState.videoDuration = videoEl.duration;
    renderTimeline();
  };

  // 获取字幕片段（从任务详情的 metadata）
  try {
    const detail = await api(`/api/jobs/${jobId}`);
    // 字幕片段可能在 output.metadata.subtitle_segments 或 steps 中
    let segments = [];
    const output = detail.output || {};
    if (output.subtitle_segments) {
      segments = output.subtitle_segments;
    }
    // 尝试从 context.json 读取
    if (!segments.length) {
      try {
        const ctxResp = await fetch(`/api/files?path=${encodeURIComponent(`workspace_data/jobs/${jobId}/context.json`)}`);
        if (ctxResp.ok) {
          const ctx = await ctxResp.json();
          if (ctx.metadata?.subtitle_segments) {
            segments = ctx.metadata.subtitle_segments;
          }
        }
      } catch (e) {}
    }
    tlState.subtitleSegments = segments;
    document.getElementById('tl-job-info').innerHTML =
      `视频: ${videoPath.split('/').pop()}<br>字幕: ${segments.length} 段`;
    renderTimeline();
  } catch (e) {
    document.getElementById('tl-job-info').textContent = `加载失败: ${e.message}`;
  }

  // 重置已添加片段
  tlState.clips = [];
  renderClipList();
}

// 渲染时间轴
function renderTimeline() {
  const duration = tlState.videoDuration || (tlState.subtitleSegments.length ?
    tlState.subtitleSegments[tlState.subtitleSegments.length - 1].end : 30);
  const container = document.getElementById('tl-timeline');
  const trackWidth = container.offsetWidth - 100 || 800;
  tlState.timelineWidth = trackWidth;
  const pxPerSec = trackWidth / duration;
  tlState.pxPerSec = pxPerSec;

  // 渲染标尺
  const ruler = document.getElementById('tl-ruler');
  ruler.innerHTML = '';
  ruler.style.width = trackWidth + 'px';
  const tickInterval = duration > 60 ? 10 : duration > 20 ? 5 : 2;
  for (let t = 0; t <= duration; t += tickInterval) {
    const x = t * pxPerSec;
    const tick = document.createElement('div');
    tick.className = 'timeline-ruler-tick';
    tick.style.left = x + 'px';
    ruler.appendChild(tick);
    const label = document.createElement('div');
    label.className = 'timeline-ruler-label';
    label.style.left = x + 'px';
    label.textContent = t + 's';
    ruler.appendChild(label);
  }

  // 主视频轨道
  const mainTrack = document.getElementById('tl-main-track');
  mainTrack.style.width = trackWidth + 'px';
  mainTrack.innerHTML = `<div class="tl-main-segment" style="left:0;width:100%">数字人口播 ${duration.toFixed(1)}s</div>`;

  // B-roll 轨道
  const brollTrack = document.getElementById('tl-broll-track');
  brollTrack.style.width = trackWidth + 'px';
  brollTrack.innerHTML = '';
  brollTrack.onclick = (e) => {
    // 点击 B-roll 轨道空白处添加片段
    if (e.target !== brollTrack) return;
    if (!tlState.selectedAsset) {
      toast('请先在左侧选择一个 B-roll 素材', 'error');
      return;
    }
    const rect = brollTrack.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const clickTime = x / pxPerSec;
    openClipModal(clickTime, duration);
  };
  // 渲染已添加的 B-roll 片段（可点击编辑）
  tlState.clips.forEach((clip, idx) => {
    const seg = document.createElement('div');
    seg.className = `tl-broll-segment ${clip.mode}`;
    seg.style.left = (clip.start * pxPerSec) + 'px';
    seg.style.width = ((clip.end - clip.start) * pxPerSec) + 'px';
    const modeIcon = clip.mode === 'pip' ? '🖼️' : '✂️';
    const transIcon = clip.transition === 'fade' ? ' 🌗' : '';
    seg.innerHTML = `${modeIcon}${transIcon} ${clip.filename || 'B-roll'}<span class="tl-segment-delete" onclick="event.stopPropagation();deleteClip(${idx})">×</span>`;
    seg.title = `${clip.mode === 'pip' ? '画中画' : '整段切换'} · ${clip.start}s-${clip.end}s · 点击编辑`;
    seg.onclick = (e) => {
      e.stopPropagation();
      openClipModalForEdit(idx);
    };
    brollTrack.appendChild(seg);
  });

  // 字幕轨道 + 字幕间插入点
  const subTrack = document.getElementById('tl-subtitle-track');
  subTrack.style.width = trackWidth + 'px';
  subTrack.innerHTML = '';
  if (tlState.subtitleSegments.length === 0) {
    subTrack.innerHTML = '<div style="color:#666;font-size:11px;padding:0 8px;line-height:32px">无字幕数据（仍可点击 B-roll 轨道插入）</div>';
  } else {
    tlState.subtitleSegments.forEach((seg, i) => {
      const el = document.createElement('div');
      el.className = 'tl-subtitle-segment';
      el.style.left = (seg.start * pxPerSec) + 'px';
      el.style.width = ((seg.end - seg.start) * pxPerSec) + 'px';
      el.textContent = seg.text || '';
      el.title = `${seg.start.toFixed(1)}s - ${seg.end.toFixed(1)}s: ${seg.text || ''}`;
      subTrack.appendChild(el);

      // 在当前字幕结束后、下一段字幕开始前插入 "+" 按钮（字幕间隙）
      if (i < tlState.subtitleSegments.length - 1) {
        const nextSeg = tlState.subtitleSegments[i + 1];
        const gapStart = seg.end;
        const gapEnd = nextSeg.start;
        if (gapEnd > gapStart + 0.1) {
          const gapMid = (gapStart + gapEnd) / 2;
          const insertBtn = document.createElement('div');
          insertBtn.className = 'tl-insert-point';
          insertBtn.style.left = (gapMid * pxPerSec) + 'px';
          insertBtn.textContent = '+';
          insertBtn.title = `在字幕间插入 B-roll（${gapStart.toFixed(1)}s - ${gapEnd.toFixed(1)}s 间隙）`;
          insertBtn.onclick = (e) => {
            e.stopPropagation();
            if (!tlState.selectedAsset) {
              toast('请先在左侧选择一个 B-roll 素材', 'error');
              return;
            }
            // 默认填充整个间隙
            openClipModal(gapStart, gapEnd, true);
          };
          subTrack.appendChild(insertBtn);
        }
      }
    });
  }
}

// 加载 B-roll 素材库
async function loadBrollAssets() {
  try {
    const assets = await api('/api/broll/assets');
    tlState.brollAssets = assets;
    renderBrollAssets();
  } catch (e) {
    // 素材库可能为空
    tlState.brollAssets = [];
    renderBrollAssets();
  }
}

// 渲染素材库
function renderBrollAssets() {
  const list = document.getElementById('tl-broll-list');
  if (!tlState.brollAssets.length) {
    list.innerHTML = '<div style="text-align:center;color:#666;font-size:12px;padding:16px">暂无素材，请上传</div>';
    return;
  }
  list.innerHTML = tlState.brollAssets.map(a => {
    const sizeStr = a.size > 1024*1024 ? (a.size/1024/1024).toFixed(1)+'MB' : Math.round(a.size/1024)+'KB';
    const icon = a.kind === 'video' ? '🎬' : '🖼️';
    const thumb = a.kind === 'image'
      ? `<img src="/api/broll/assets/${encodeURIComponent(a.filename)}" onerror="this.parentElement.innerHTML='${icon}'">`
      : icon;
    return `
      <div class="broll-asset-card ${tlState.selectedAsset?.path === a.path ? 'selected' : ''}"
           onclick="selectBrollAsset('${a.path}','${a.filename}','${a.kind}')">
        <div class="broll-asset-thumb">${thumb}</div>
        <div class="broll-asset-info">
          <div class="broll-asset-name">${a.filename}</div>
          <div class="broll-asset-meta">${a.kind === 'video' ? '视频' : '图片'} · ${sizeStr}</div>
        </div>
      </div>
    `;
  }).join('');
}

// 选择素材
function selectBrollAsset(path, filename, kind) {
  tlState.selectedAsset = { path, filename, kind };
  renderBrollAssets();
  toast(`已选择素材: ${filename}`, 'success');
}

// 上传 B-roll 素材
async function onBrollUpload(input) {
  const file = input.files[0];
  if (!file) return;
  document.getElementById('tl-upload-text').textContent = file.name;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const resp = await fetch('/api/broll/upload', { method: 'POST', body: formData });
    const result = await resp.json();
    if (result.success) {
      toast(`素材上传成功: ${result.filename}`, 'success');
      await loadBrollAssets();
      // 自动选中新上传的素材
      selectBrollAsset(result.path, result.filename, file.type.startsWith('video/') ? 'video' : 'image');
      document.getElementById('tl-upload-text').textContent = '点击上传视频/图片';
    } else {
      toast('上传失败', 'error');
    }
  } catch (e) {
    toast(`上传失败: ${e.message}`, 'error');
  }
  input.value = '';
}

// 打开片段编辑弹窗（新增模式）
// clickTime: 开始时间；endOrDuration: 若 fillGap=true 则为结束时间，否则为视频总时长
function openClipModal(clickTime, endOrDuration, fillGap = false) {
  const asset = tlState.selectedAsset;
  let startT, endT;
  if (fillGap) {
    // 字幕间隙插入：clickTime=间隙开始，endOrDuration=间隙结束
    startT = clickTime;
    endT = endOrDuration;
  } else {
    // 点击轨道：默认时长 3 秒，不超过视频剩余时长
    const defaultDur = Math.min(3, endOrDuration - clickTime);
    startT = clickTime;
    endT = clickTime + defaultDur;
  }
  tlState.editingClipIdx = -1;
  tlState.pendingClip = {
    path: asset.path,
    filename: asset.filename,
    kind: asset.kind,
    start: parseFloat(startT.toFixed(1)),
    end: parseFloat(endT.toFixed(1)),
    mode: 'pip',
    position: 'bottom_right',
    scale: 0.3,
    volume: 0,
    transition: 'none',
  };
  fillClipModalForm(tlState.pendingClip);
  document.getElementById('tl-clip-modal').style.display = '';
  document.querySelector('#tl-clip-modal .modal-title').textContent = '添加 B-roll 片段';
  document.querySelector('#tl-clip-modal .btn-primary').textContent = '添加片段';
}

// 打开片段编辑弹窗（编辑已有片段）
function openClipModalForEdit(idx) {
  const clip = tlState.clips[idx];
  if (!clip) return;
  tlState.editingClipIdx = idx;
  tlState.pendingClip = { ...clip };
  fillClipModalForm(clip);
  document.getElementById('tl-clip-modal').style.display = '';
  document.querySelector('#tl-clip-modal .modal-title').textContent = '编辑 B-roll 片段';
  document.querySelector('#tl-clip-modal .btn-primary').textContent = '保存修改';
}

// 填充弹窗表单
function fillClipModalForm(clip) {
  document.getElementById('clip-start').value = clip.start;
  document.getElementById('clip-end').value = clip.end;
  document.querySelector(`input[name="clip-mode"][value="${clip.mode || 'pip'}"]`).checked = true;
  document.getElementById('clip-position').value = clip.position || 'bottom_right';
  document.getElementById('clip-scale').value = clip.scale || 0.3;
  document.getElementById('clip-scale-val').textContent = Math.round((clip.scale || 0.3) * 100) + '%';
  document.getElementById('clip-volume').value = clip.volume || 0;
  document.getElementById('clip-volume-val').textContent = Math.round((clip.volume || 0) * 100) + '%';
  document.getElementById('clip-transition').value = clip.transition || 'none';
  onClipModeChange();
}

// 模式切换时显示/隐藏画中画设置
function onClipModeChange() {
  const mode = document.querySelector('input[name="clip-mode"]:checked').value;
  const pipSettings = document.getElementById('clip-pip-settings');
  const scaleGroup = document.getElementById('clip-scale-group');
  if (mode === 'pip') {
    pipSettings.style.display = '';
    scaleGroup.style.display = '';
  } else {
    pipSettings.style.display = 'none';
    scaleGroup.style.display = 'none';
  }
}

// 关闭弹窗
function closeClipModal() {
  document.getElementById('tl-clip-modal').style.display = 'none';
  tlState.pendingClip = null;
  tlState.editingClipIdx = -1;
}

// 确认添加/保存片段
function confirmAddClip() {
  if (!tlState.pendingClip) return;
  const start = parseFloat(document.getElementById('clip-start').value);
  const end = parseFloat(document.getElementById('clip-end').value);
  if (isNaN(start) || isNaN(end) || end <= start) {
    toast('时间设置无效，结束时间必须大于开始时间', 'error');
    return;
  }
  const mode = document.querySelector('input[name="clip-mode"]:checked').value;
  const clip = {
    ...tlState.pendingClip,
    start,
    end,
    mode,
    position: document.getElementById('clip-position').value,
    scale: parseFloat(document.getElementById('clip-scale').value),
    volume: parseFloat(document.getElementById('clip-volume').value),
    transition: document.getElementById('clip-transition').value,
  };
  if (tlState.editingClipIdx >= 0) {
    // 编辑模式：替换已有片段
    tlState.clips[tlState.editingClipIdx] = clip;
    toast(`已更新片段 (${start}s-${end}s)`, 'success');
  } else {
    // 新增模式
    tlState.clips.push(clip);
    toast(`已添加 ${mode === 'pip' ? '画中画' : '整段切换'} 片段 (${start}s-${end}s)`, 'success');
  }
  closeClipModal();
  renderTimeline();
  renderClipList();
}

// 渲染已添加片段列表
function renderClipList() {
  const list = document.getElementById('tl-clip-list');
  if (!tlState.clips.length) {
    list.innerHTML = '<div style="text-align:center;color:#666;font-size:12px;padding:12px">暂无 B-roll 片段，点击字幕间的 + 或 B-roll 轨道添加</div>';
    return;
  }
  list.innerHTML = tlState.clips.map((clip, idx) => {
    const modeLabel = clip.mode === 'pip' ? '画中画' : '整段切换';
    const posLabel = clip.mode === 'pip' ? ` · ${clip.position} · ${Math.round(clip.scale*100)}%` : '';
    const transLabel = clip.transition === 'fade' ? ' · 淡入淡出' : '';
    return `
      <div class="tl-clip-item">
        <span class="clip-badge ${clip.mode}">${modeLabel}</span>
        <span>${clip.filename}</span>
        <span style="color:#666">${clip.start}s - ${clip.end}s${posLabel}${transLabel}</span>
        <span class="clip-edit" onclick="openClipModalForEdit(${idx})" title="编辑">✏️</span>
        <span class="clip-delete" onclick="deleteClip(${idx})" title="删除">🗑️</span>
      </div>
    `;
  }).join('');
}

// 删除片段
function deleteClip(idx) {
  tlState.clips.splice(idx, 1);
  renderTimeline();
  renderClipList();
}

// 清空所有片段
function clearAllBrollClips() {
  if (!tlState.clips.length) return;
  if (!confirm('确定清空所有 B-roll 片段？')) return;
  tlState.clips = [];
  renderTimeline();
  renderClipList();
}

// 应用 B-roll 合成
async function applyBrollToVideo() {
  if (!tlState.videoPath) {
    toast('请先选择任务', 'error');
    return;
  }
  if (!tlState.clips.length) {
    toast('请先添加 B-roll 片段', 'error');
    return;
  }
  const btn = document.getElementById('tl-apply-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 合成中...';

  try {
    const formData = new FormData();
    formData.append('video_path', tlState.videoPath);
    formData.append('clips_json', JSON.stringify(tlState.clips));
    const resp = await fetch('/api/broll/apply', { method: 'POST', body: formData });
    const result = await resp.json();
    if (result.success) {
      toast(`B-roll 合成成功！输出: ${result.output_path.split('/').pop()}`, 'success');
      // 更新预览为合成后的视频
      document.getElementById('tl-video-preview').src = `/api/files?path=${encodeURIComponent(result.output_path)}`;
    } else {
      toast(`合成失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`合成失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '应用 B-roll 合成';
  }
}

// 在播放头位置插入 B-roll
function insertBrollAtPlayhead() {
  if (!tlState.videoPath) {
    toast('请先选择任务', 'error');
    return;
  }
  if (!tlState.selectedAsset) {
    toast('请先在左侧选择一个 B-roll 素材', 'error');
    return;
  }
  const videoEl = document.getElementById('tl-video-preview');
  const clickTime = videoEl.currentTime || 0;
  const duration = tlState.videoDuration || (tlState.subtitleSegments.length ?
    tlState.subtitleSegments[tlState.subtitleSegments.length - 1].end : 30);
  openClipModal(clickTime, duration);
}

// ===== 快捷剪辑（裁剪/音量/淡入淡出） =====

// 打开快捷剪辑弹窗
function openQuickEditModal(action) {
  if (!tlState.videoPath) {
    toast('请先选择任务', 'error');
    return;
  }
  tlState.quickEditAction = action;
  const titles = { trim: '✂️ 裁剪视频', volume: '🔊 调整音量', fade: '🌗 淡入淡出' };
  document.getElementById('qe-title').textContent = titles[action] || '快捷剪辑';
  const duration = tlState.videoDuration || 0;
  const body = document.getElementById('qe-body');

  if (action === 'trim') {
    body.innerHTML = `
      <div class="form-group">
        <label class="form-label">开始时间（秒）<span style="color:#999"> · 视频总长 ${duration.toFixed(1)}s</span></label>
        <input type="number" class="form-input" id="qe-trim-start" min="0" max="${duration.toFixed(1)}" step="0.1" value="0">
      </div>
      <div class="form-group">
        <label class="form-label">结束时间（秒）</label>
        <input type="number" class="form-input" id="qe-trim-end" min="0" max="${duration.toFixed(1)}" step="0.1" value="${duration.toFixed(1)}">
      </div>
      <div style="font-size:12px;color:#999">保留 [开始, 结束] 区间，裁掉头尾</div>
    `;
  } else if (action === 'volume') {
    body.innerHTML = `
      <div class="form-group">
        <label class="form-label">音量倍数 <span id="qe-vol-val" style="color:#666">1.0x（原音量）</span></label>
        <input type="range" id="qe-vol" min="0" max="2" step="0.1" value="1.0" oninput="document.getElementById('qe-vol-val').textContent=this.value+'x'">
      </div>
      <div style="font-size:12px;color:#999">0=静音，1.0=原音量，2.0=两倍音量</div>
    `;
  } else if (action === 'fade') {
    body.innerHTML = `
      <div class="form-group">
        <label class="form-label">片头淡入时长（秒） <span id="qe-fi-val" style="color:#666">0.5s</span></label>
        <input type="range" id="qe-fi" min="0" max="3" step="0.1" value="0.5" oninput="document.getElementById('qe-fi-val').textContent=this.value+'s'">
      </div>
      <div class="form-group">
        <label class="form-label">片尾淡出时长（秒） <span id="qe-fo-val" style="color:#666">0.5s</span></label>
        <input type="range" id="qe-fo" min="0" max="3" step="0.1" value="0.5" oninput="document.getElementById('qe-fo-val').textContent=this.value+'s'">
      </div>
      <div style="font-size:12px;color:#999">画面与声音同步淡入淡出</div>
    `;
  }
  document.getElementById('tl-quickedit-modal').style.display = '';
}

// 关闭快捷剪辑弹窗
function closeQuickEditModal() {
  document.getElementById('tl-quickedit-modal').style.display = 'none';
  tlState.quickEditAction = '';
}

// 确认快捷剪辑
async function confirmQuickEdit() {
  const action = tlState.quickEditAction;
  if (!action || !tlState.videoPath) return;
  let params = {};
  if (action === 'trim') {
    params.start = parseFloat(document.getElementById('qe-trim-start').value) || 0;
    params.end = parseFloat(document.getElementById('qe-trim-end').value) || 0;
    if (params.end <= params.start) {
      toast('结束时间必须大于开始时间', 'error');
      return;
    }
  } else if (action === 'volume') {
    params.volume = parseFloat(document.getElementById('qe-vol').value);
  } else if (action === 'fade') {
    params.fade_in = parseFloat(document.getElementById('qe-fi').value);
    params.fade_out = parseFloat(document.getElementById('qe-fo').value);
  }

  const btn = document.getElementById('qe-confirm-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 处理中...';
  try {
    const formData = new FormData();
    formData.append('video_path', tlState.videoPath);
    formData.append('action', action);
    formData.append('params_json', JSON.stringify(params));
    const resp = await fetch('/api/video/quick-edit', { method: 'POST', body: formData });
    const result = await resp.json();
    if (result.success) {
      toast(`剪辑成功: ${result.output_path.split('/').pop()}`, 'success');
      // 更新预览为处理后的视频
      tlState.videoPath = result.output_path;
      document.getElementById('tl-video-preview').src = `/api/files?path=${encodeURIComponent(result.output_path)}`;
      closeQuickEditModal();
    } else {
      toast(`剪辑失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`剪辑失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '应用';
  }
}
