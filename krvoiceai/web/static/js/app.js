/**
 * EnlyAI Web App
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
  } else if (opts.body instanceof FormData) {
    // FormData：让浏览器自动设置 multipart Content-Type（含 boundary），不能手动指定
    delete opts.headers['Content-Type'];
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
  const icons = {
    success: '<i data-lucide="check" style="width:18px;height:18px"></i>',
    error: '<i data-lucide="x" style="width:18px;height:18px"></i>',
    info: '<i data-lucide="info" style="width:18px;height:18px"></i>',
    warning: '<i data-lucide="alert-triangle" style="width:18px;height:18px"></i>'
  };
  el.innerHTML = `<span style="display:inline-flex;align-items:center">${icons[type] || ''}</span><span>${message}</span>`;
  container.appendChild(el);
  if (window.lucide) lucide.createIcons();
  // 点击可提前关闭
  el.style.cursor = 'pointer';
  el.addEventListener('click', () => {
    el.style.animation = 'slideIn 0.3s ease reverse';
    setTimeout(() => el.remove(), 300);
  });
  setTimeout(() => {
    if (el.parentNode) {
      el.style.animation = 'slideIn 0.3s ease reverse';
      setTimeout(() => el.remove(), 300);
    }
  }, 4000);
}

// 图片加载失败时回退为 Lucide 图标（供 onerror 内联调用）
function setFallbackIcon(parent, lucideName) {
  parent.innerHTML = `<i data-lucide="${lucideName}"></i>`;
  if (window.lucide) lucide.createIcons();
}

// 设置按钮为「Lucide 图标 + 文字」并渲染图标
function setBtnIcon(btn, lucideName, text) {
  btn.innerHTML = text ? `<i data-lucide="${lucideName}"></i> ${text}` : `<i data-lucide="${lucideName}"></i>`;
  if (window.lucide) lucide.createIcons();
}

// ========== 骨架屏（Skeleton Screen）工具 ==========

/**
 * 在容器内显示骨架屏卡片网格
 * @param {HTMLElement} container - 目标容器
 * @param {number} count - 骨架卡片数量
 */
function showSkeletonCards(container, count = 6) {
  if (!container) return;
  const cols = container.dataset.gridCols || 3;
  container.innerHTML = '';
  container.style.display = 'grid';
  container.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  container.style.gap = '16px';
  for (let i = 0; i < count; i++) {
    const card = document.createElement('div');
    card.className = 'skeleton-card';
    card.innerHTML = `
      <div class="skeleton skeleton-thumb"></div>
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-meta"></div>
    `;
    container.appendChild(card);
  }
}

/**
 * 在容器内显示骨架屏行列表（用于表格/列表）
 * @param {HTMLElement} container - 目标容器
 * @param {number} count - 骨架行数量
 */
function showSkeletonRows(container, count = 5) {
  if (!container) return;
  container.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const row = document.createElement('div');
    row.className = 'skeleton-row';
    row.innerHTML = `
      <div class="skeleton skeleton-avatar"></div>
      <div class="skeleton-content">
        <div class="skeleton skeleton-line long"></div>
        <div class="skeleton skeleton-line short"></div>
      </div>
    `;
    container.appendChild(row);
  }
}

/**
 * 在容器内显示骨架屏文本行（用于简单文本列表）
 * @param {HTMLElement} container - 目标容器
 * @param {number} count - 骨架行数量
 */
function showSkeletonLines(container, count = 4) {
  if (!container) return;
  container.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const line = document.createElement('div');
    line.className = 'skeleton skeleton-line';
    line.classList.add(i % 3 === 0 ? 'medium' : 'long');
    container.appendChild(line);
  }
}

// ========== 表单校验工具 ==========

/**
 * 设置输入框错误状态
 * @param {HTMLElement} input - 输入框元素
 * @param {string} msg - 错误信息（空则清除错误）
 */
function setFieldError(input, msg = '') {
  if (!input) return;
  input.classList.remove('error', 'success');
  if (msg) {
    input.classList.add('error');
  }
  // 查找或创建 field-error 元素
  let errEl = input.parentNode.querySelector('.field-error');
  if (!errEl) {
    errEl = document.createElement('span');
    errEl.className = 'field-error';
    input.parentNode.insertBefore(errEl, input.nextSibling);
  }
  errEl.textContent = msg;
}

/**
 * 设置输入框成功状态
 */
function setFieldSuccess(input) {
  if (!input) return;
  input.classList.remove('error');
  input.classList.add('success');
  const errEl = input.parentNode.querySelector('.field-error');
  if (errEl) errEl.textContent = '';
}

/**
 * URL 格式校验
 * @param {string} url
 * @returns {boolean}
 */
function isValidUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * ID 格式校验（英文字母+数字，3-32位）
 * @param {string} id
 * @returns {boolean}
 */
function isValidId(id) {
  return /^[a-zA-Z0-9]{3,32}$/.test(id);
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
  'dashboard', 'wizard', 'podcast', 'generate', 'script', 'step-by-step', 'batch', 'timeline',
  'avatars', 'voices', 'templates', 'jobs',
  'settings-models', 'settings-video', 'settings-scene', 'settings-publish',
  'health',
];

function navigate(page) {
  // 切换页面时停止所有试听音频（避免后台继续播放）
  stopAllPreviewAudio();
  PAGES.forEach(p => {
    const pageEl = document.getElementById(`page-${p}`);
    if (pageEl) pageEl.classList.remove('active');
  });
  // 清除所有侧边栏导航项的 active（含分组导航 nav-resources / nav-settings）
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(n => n.classList.remove('active'));

  const targetPage = document.getElementById(`page-${page}`);
  const targetNav = document.getElementById(`nav-${page}`);
  if (targetPage) targetPage.classList.add('active');
  if (targetNav) targetNav.classList.add('active');

  // 资源中心 / 设置中心 分组导航高亮
  const NAV_GROUP = {
    avatars: 'nav-resources', voices: 'nav-resources', templates: 'nav-resources',
    'settings-models': 'nav-settings', 'settings-video': 'nav-settings',
    'settings-scene': 'nav-settings', 'settings-publish': 'nav-settings',
  };
  const groupNavId = NAV_GROUP[page];
  if (groupNavId) {
    const gNav = document.getElementById(groupNavId);
    if (gNav) gNav.classList.add('active');
  }

  // 更新底部导航栏激活状态（移动端，按分组映射）
  const BOTTOM_GROUP = {
    avatars: 'avatars', voices: 'avatars', templates: 'avatars',
    'settings-models': 'settings-models', 'settings-video': 'settings-models',
    'settings-scene': 'settings-models', 'settings-publish': 'settings-models',
  };
  const activeBottom = BOTTOM_GROUP[page] || page;
  document.querySelectorAll('.bottom-nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.page === activeBottom);
  });

  // 同步资源中心 / 设置中心内部 Tab 高亮
  syncResourceSettingsTabs(page);

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
  if (page === 'podcast') initPodcast();
  if (page === 'templates') { loadTemplatesCenter(); loadSceneTemplates(); loadPresetAvatars(); loadPresetVoices(); }
  if (page === 'generate') { loadAvatarsForSelect(); loadVoicesForSelect(); }
  if (page === 'step-by-step') { loadAvatarsForSelect2(); loadVoicesForSelect2(); }
  if (page === 'batch') { loadAvatarsForSelect3(); loadVoicesForSelect3(); }
  if (page === 'timeline') initTimelineEditor();
  if (page === 'settings-models') loadAllSettings();
  if (page === 'settings-video') loadVideoSettings();
  if (page === 'settings-scene') loadSceneEffectSettings();
  if (page === 'settings-publish') loadPublishSettings();

  // 切换页面后重新渲染 Lucide 图标（覆盖动态生成的内容）
  if (window.lucide) lucide.createIcons();
}

// 资源中心 / 设置中心 内部 Tab 高亮同步（页面切换时调用）
function syncResourceSettingsTabs(page) {
  const resourceMap = { avatars: 'avatars', voices: 'voices', templates: 'templates' };
  const rTarget = resourceMap[page];
  document.querySelectorAll('.resource-tab').forEach(t => {
    const on = t.dataset.target === rTarget;
    t.classList.toggle('active', on);
    t.style.color = on ? 'var(--primary)' : 'var(--text-muted)';
    t.style.borderBottom = on ? '2px solid var(--primary)' : 'none';
    t.style.fontWeight = on ? '600' : 'normal';
  });
  const settingsMap = {
    'settings-models': 'settings-models', 'settings-video': 'settings-video',
    'settings-scene': 'settings-scene', 'settings-publish': 'settings-publish',
  };
  const sTarget = settingsMap[page];
  document.querySelectorAll('.settings-tab').forEach(t => {
    const on = t.dataset.target === sTarget;
    t.classList.toggle('active', on);
    t.style.color = on ? 'var(--primary)' : 'var(--text-muted)';
    t.style.borderBottom = on ? '2px solid var(--primary)' : 'none';
    t.style.fontWeight = on ? '600' : 'normal';
  });
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
  showSkeletonRows(container, 4);
  try {
    const jobs = await api('/api/jobs?limit=8');
    if (!jobs || !jobs.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="film"></i></div><div>还没有创作记录，点击上方按钮开始吧</div></div>';
      if (window.lucide) lucide.createIcons();
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
        ? `<img src="/api/files?path=${encodeURIComponent(coverPath)}" alt="封面" onerror="setFallbackIcon(this.parentElement,'film')">`
        : '<i data-lucide="film"></i>';
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
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="film"></i></div><div>加载失败，请稍后重试</div></div>';
    if (window.lucide) lucide.createIcons();
  }
}

async function loadDashboardTemplates() {
  const grid = document.getElementById('dash-template-grid');
  if (!grid) return;
  showSkeletonCards(grid, 6);
  try {
    const templates = await ensureTemplates();
    const entries = Object.entries(templates).slice(0, 6);
    grid.innerHTML = entries.map(([key, tpl]) => `
      <div class="template-card" data-key="${key}">
        <div class="template-card-icon"><i data-lucide="${tpl.icon}"></i></div>
        <div class="template-card-label">${tpl.label}</div>
        <div class="template-card-desc">${tpl.description}</div>
        <div class="template-card-tags">
          <span class="template-card-tag">${tpl.subtitle_preset}</span>
          <span class="template-card-tag">${tpl.emotion}</span>
        </div>
      </div>
    `).join('');
    if (window.lucide) lucide.createIcons();
    grid.querySelectorAll('.template-card').forEach(card => {
      card.addEventListener('click', () => applyDashboardTemplate(card.dataset.key));
    });
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="palette"></i></div><div>模板加载失败</div></div>';
    if (window.lucide) lucide.createIcons();
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
  maxVisitedStep: 1,  // 通过下一步逐步到达过的最大步骤（跳跃点击不更新，避免前面步骤误标勾）
  selectedTemplate: null,
  selectedTemplateObj: null,  // 当前选中的模板完整对象（含 script_template/placeholders/avatar_scene）
  selectedSubtitleStyle: 'douyin_hot',
  wizScriptTab: 'manual',
  wizScriptAction: 'polish',
  initialized: false,
  sceneCategory: null,  // 从首页场景卡带入的分类
  scriptProcessed: false,  // 文案是否已经过提取/AI处理（true=生成时跳过重复polish和重复提取）
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
  // provider 切换后缓存被置空（settings.js 设为 null），需重新加载音色库
  if (!wizardState.initialized || !window._wizardVoiceList) {
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
    // 步骤1：模板和预设优先渲染（快请求，不阻塞）
    const [presets, templates] = await Promise.all([
      ensureCreativePresets(),
      ensureTemplates(),
    ]);
    renderWizardTemplateGrid(templates);
    renderBtnCardGrid('wiz-pose-grid', presets.poses, POSE_ICONS);
    setBtnCardValue('wiz-pose-grid', 'half_body');
    bindBtnCardGrid('wiz-pose-grid');
    // 非 half_body 的 pose 暂未支持，标注即将支持并禁用
    document.querySelectorAll('#wiz-pose-grid .btn-card').forEach(btn => {
      if (btn.dataset.value !== 'half_body') {
        const label = btn.querySelector('.btn-card-label');
        if (label) label.textContent += ' (即将支持)';
        btn.disabled = true;
        btn.title = '即将支持';
      }
    });
    bindBtnCardGrid('wiz-position-grid');
    bindBtnCardGrid('wiz-bg-type-grid', (val) => {
      document.getElementById('wiz-bg-color-group').style.display = val === 'solid' ? 'block' : 'none';
      document.getElementById('wiz-bg-image-group').style.display = val === 'image' ? 'block' : 'none';
    });

    // 步骤2：慢请求（BGM/形象/音色）并行加载，不阻塞模板渲染
    // 先显示骨架屏，避免10s空白让用户以为卡住
    const _avatarGrid = document.getElementById('wiz-avatar-grid');
    const _voiceGrid = document.getElementById('wiz-voice-grid');
    if (_avatarGrid) showSkeletonCards(_avatarGrid, 4);
    if (_voiceGrid) showSkeletonCards(_voiceGrid, 4);
    Promise.all([
      ensureBgmLibrary(),
      api('/api/avatars').catch(() => []),
      api('/api/voices').catch(() => []),
      api('/api/presets/avatars').catch(() => ({ avatars: {} })),
      api('/api/settings').catch(() => null),  // 新增：加载设置中心配置回填向导
    ]).then(([bgmLib, avatars, voices, presetAvatars, settings]) => {
      // 构建 avatar_id -> gender 映射（用于形象与音色性别联动）
      const avatarGenderMap = {};
      if (presetAvatars && presetAvatars.avatars) {
        Object.entries(presetAvatars.avatars).forEach(([aid, info]) => {
          avatarGenderMap[aid] = info.gender || '';
        });
      }
      window._wizardVoiceList = voices || [];
      renderWizardAvatarGrid(avatars, avatarGenderMap);
      renderWizardVoiceGrid(voices);
      // BGM 曲目
      const bgmSel = document.getElementById('wiz-bgm-track');
      if (bgmSel) {
        bgmSel.innerHTML = Object.entries(bgmLib).map(([key, info]) =>
          `<option value="${key}">${info.label}（${info.mood}）</option>`
        ).join('');
      }
      // 从设置中心回填向导所有控件
      _applySettingsToWizard(settings);
    });

    // 步骤3：文案 Tab 切换
    document.querySelectorAll('[data-wiztab]').forEach(tab => {
      tab.addEventListener('click', () => {
        wizardState.wizScriptTab = tab.dataset.wiztab;
        document.querySelectorAll('[data-wiztab]').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('wiz-script-manual')?.classList.remove('active');
        document.getElementById('wiz-script-ai')?.classList.remove('active');
        document.getElementById('wiz-script-extract')?.classList.remove('active');
        document.getElementById('wiz-script-' + tab.dataset.wiztab)?.classList.add('active');
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
    window._subtitleStylePresets = presets.subtitle_styles;  // 保存供 _applySettingsToWizard 使用
    renderSubtitleStyleGrid('wiz-subtitle-style-grid', presets.subtitle_styles, 'douyin_hot', (key) => {
      wizardState.selectedSubtitleStyle = key;
      applySubtitleStylePreset(key);
    });
    fillSelect('wiz-sub-anim', presets.subtitle_animations);
    fillSelect('wiz-transition', presets.transitions);
    fillSelect('wiz-filter', presets.filters);

    // 联动 P3：动态加载发布平台选择（带登录态校验）
    loadWizardPublishPlatforms();


    // 开关联动
    document.getElementById('wiz-show-logo').addEventListener('change', e => {
      document.getElementById('wiz-logo-position-group').style.display = e.target.checked ? 'block' : 'none';
      document.getElementById('wiz-logo-image-group').style.display = e.target.checked ? 'block' : 'none';
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
      // 文案变化时自动刷新画中画字幕时间轴（若已启用）
      const brollEnabled = document.getElementById('wiz-broll-enabled')?.checked;
      if (brollEnabled) {
        autoLoadWizardSubtitles();
        renderWizardTimeline();
      }
    });

    // 文案 AI 工具栏
    bindScriptToolbar();

    // 绑定向导按钮
    document.getElementById('wizard-apply-template-btn').addEventListener('click', wizardApplyTemplate);
    document.getElementById('wizard-skip-template-btn').addEventListener('click', wizardSkipTemplate);
    document.getElementById('wiz-ai-generate-btn').addEventListener('click', wizardAiGenerate);
    document.getElementById('wiz-extract-btn').addEventListener('click', wizardExtractScript);
    bindShareTextPreview(); // 分享文本实时解析预览
    // 自由创作卡片：取消模板选择
    const freeCard = document.querySelector('#wiz-template-grid .template-card[data-tplid=""]');
    if (freeCard) freeCard.addEventListener('click', () => selectScriptTemplate(freeCard, { name: '自由创作', structure: '不套用模板，由 AI 自由发挥' }));
    loadScriptTemplates(); // 异步加载爆款模板卡片
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
    if (window.lucide) lucide.createIcons();

    // 联动 P1：注册设置变更事件监听器
    // 设置中心保存配置后广播 enlyai:settings-changed 事件，向导实时刷新
    if (!window._wizardSettingsChangeListener) {
      window._wizardSettingsChangeListener = true;
      window.addEventListener('enlyai:settings-changed', async (e) => {
        try {
          const section = e?.detail?.section;
          // 重新拉取最新设置并回填向导
          const settings = await api('/api/settings').catch(() => null);
          if (!settings) return;
          _applySettingsToWizard(settings);
          // 如果是 TTS 变更，需要刷新音色列表（provider 可能变了）
          if (section === 'tts') {
            const voices = await api('/api/voices').catch(() => []);
            window._wizardVoiceList = voices;
            renderWizardVoiceGrid(voices);
          }
          // 如果是 publisher 变更，需要刷新平台选择（启用状态可能变了）
          if (section === 'publisher') {
            await loadWizardPublishPlatforms();
          }
          console.debug(`[向导] 设置变更已同步: section=${section}`);
        } catch (err) {
          console.warn('[向导] 设置变更同步失败:', err);
        }
      });
    }

    // 联动 P2：注册形象/音色变更事件监听器
    // 资源中心注册新形象/音色后广播 enlyai:avatars-changed / enlyai:voices-changed，向导自动刷新
    if (!window._wizardAvatarsChangeListener) {
      window._wizardAvatarsChangeListener = true;
      window.addEventListener('enlyai:avatars-changed', async () => {
        try {
          const [avatars, presetAvatars] = await Promise.all([
            api('/api/avatars').catch(() => []),
            api('/api/presets/avatars').catch(() => ({ avatars: {} })),
          ]);
          const avatarGenderMap = {};
          if (presetAvatars && presetAvatars.avatars) {
            Object.entries(presetAvatars.avatars).forEach(([aid, info]) => {
              avatarGenderMap[aid] = info.gender || '';
            });
          }
          renderWizardAvatarGrid(avatars, avatarGenderMap);
          // 重新应用设置中的默认形象选中状态
          const settings = await api('/api/settings').catch(() => null);
          if (settings) _applySettingsToWizard(settings);
          toast('已同步新注册的形象到向导', 'success');
        } catch (err) {
          console.warn('[向导] 形象列表同步失败:', err);
        }
      });
    }
    if (!window._wizardVoicesChangeListener) {
      window._wizardVoicesChangeListener = true;
      window.addEventListener('enlyai:voices-changed', async () => {
        try {
          const voices = await api('/api/voices').catch(() => []);
          window._wizardVoiceList = voices;
          renderWizardVoiceGrid(voices);
          // 重新应用设置中的默认音色选中状态
          const settings = await api('/api/settings').catch(() => null);
          if (settings) _applySettingsToWizard(settings);
          toast('已同步新注册的音色到向导', 'success');
        } catch (err) {
          console.warn('[向导] 音色列表同步失败:', err);
        }
      });
    }
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
      <div class="template-card-icon"><i data-lucide="${tpl.icon}"></i></div>
      <div class="template-card-label">${tpl.label}</div>
      <div class="template-card-desc">${tpl.description}</div>
      <div class="template-card-tags">
        <span class="template-card-tag">${tpl.subtitle_preset}</span>
        <span class="template-card-tag">${tpl.emotion}</span>
        <span class="template-card-tag">${tpl.filter}</span>
        ${tpl.voice ? `<span class="template-card-tag">${tpl.voice}</span>` : ''}
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
  // 重新渲染 lucide 图标
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

// 渲染数字人卡片网格
function renderWizardAvatarGrid(avatars, genderMap) {
  const grid = document.getElementById('wiz-avatar-grid');
  if (!grid) return;
  const list = avatars && avatars.length ? avatars : [{ avatar_id: 'default', reference_image: null }];
  grid.innerHTML = list.map(a => {
    const id = a.avatar_id;
    const mode = a.meta?.mode || 'mock';
    const hasLipSync = a.meta?.has_lip_sync || mode === 'wav2lip';
    const lipBadge = hasLipSync
      ? '<span style="position:absolute;top:4px;right:4px;background:#10b981;color:#fff;font-size:9px;padding:1px 4px;border-radius:3px;display:inline-flex;align-items:center;gap:2px"><i data-lucide="smile" style="width:11px;height:11px"></i> 唇形</span>'
      : '';
    const imgHtml = `<img src="/api/avatars/${encodeURIComponent(id)}/preview" alt="${id}" onerror="setFallbackIcon(this.parentElement,'user-round')">`;
    return `
      <div class="avatar-card" data-id="${id}" style="position:relative">
        <div class="avatar-card-img">${imgHtml}${lipBadge}</div>
        <div class="avatar-card-id">${id}</div>
      </div>
    `;
  }).join('');
  if (window.lucide) lucide.createIcons();
  // 默认选中第一个
  const firstId = list[0].avatar_id;
  document.getElementById('wiz-avatar').value = firstId;
  grid.querySelectorAll('.avatar-card').forEach(card => {
    if (card.dataset.id === firstId) card.classList.add('selected');
    card.addEventListener('click', () => {
      const isSelected = card.classList.contains('selected');
      // 形象为必选项，不允许反选取消（避免数据与视觉不一致）
      if (isSelected) return;
      grid.querySelectorAll('.avatar-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      document.getElementById('wiz-avatar').value = card.dataset.id;
      // 形象与音色性别联动：选中形象时自动推荐同性别音色
      _linkAvatarToVoice(card.dataset.id, genderMap || {});
    });
  });
}

// 形象与音色性别联动：选中形象时自动推荐同性别音色
function _linkAvatarToVoice(avatarId, genderMap) {
  const gender = genderMap[avatarId];
  if (!gender || !window._wizardVoiceList || !window._wizardVoiceList.length) return;
  // 找同性别的第一个音色
  const matchedVoice = window._wizardVoiceList.find(v => v.gender === gender);
  if (!matchedVoice) return;
  const voiceGrid = document.getElementById('wiz-voice-grid');
  if (!voiceGrid) return;
  // 如果目标音色已选中，不重复操作
  const currentSelected = voiceGrid.querySelector('.voice-card.selected');
  if (currentSelected && currentSelected.dataset.id === matchedVoice.voice_id) return;
  // 取消所有音色选中，选中匹配的音色
  voiceGrid.querySelectorAll('.voice-card').forEach(c => c.classList.remove('selected'));
  const targetCard = voiceGrid.querySelector(`.voice-card[data-id="${matchedVoice.voice_id}"]`);
  if (targetCard) {
    targetCard.classList.add('selected');
    document.getElementById('wiz-voice').value = matchedVoice.voice_id;
    // 更新emotion支持状态
    const supports = targetCard.dataset.supportsEmotion === '1';
    const emotionGrid = document.getElementById('wiz-emotion-grid');
    const emotionHint = document.getElementById('wiz-emotion-hint');
    if (emotionGrid) {
      emotionGrid.style.opacity = supports ? '1' : '0.4';
      emotionGrid.style.pointerEvents = supports ? 'auto' : 'none';
    }
    if (emotionHint) emotionHint.style.display = supports ? 'none' : 'block';
    toast(`已自动推荐${gender === 'female' ? '女声' : '男声'}：${matchedVoice.label}`, 'info');
  }
}

// 将设置中心配置回填到向导所有控件（实现设置↔向导联动）
function _applySettingsToWizard(settings) {
  if (!settings) return;
  try {
    // ===== 步骤2：场景配置 =====
    const scene = settings.scene || {};
    if (scene.pose) setBtnCardValue('wiz-pose-grid', scene.pose);
    if (scene.position) setBtnCardValue('wiz-position-grid', scene.position);
    if (scene.scale != null) { const el = document.getElementById('wiz-scale'); if (el) el.value = scene.scale; }
    if (scene.background_type) {
      setBtnCardValue('wiz-bg-type-grid', scene.background_type);
      document.getElementById('wiz-bg-color-group').style.display = scene.background_type === 'solid' ? 'block' : 'none';
      document.getElementById('wiz-bg-image-group').style.display = scene.background_type === 'image' ? 'block' : 'none';
    }
    if (scene.background_color) { const el = document.getElementById('wiz-bg-color'); if (el) el.value = scene.background_color; }
    if (scene.background_image) { const el = document.getElementById('wiz-bg-image'); if (el) el.value = scene.background_image; }
    if (scene.show_logo != null) {
      document.getElementById('wiz-show-logo').checked = !!scene.show_logo;
      document.getElementById('wiz-logo-position-group').style.display = scene.show_logo ? 'block' : 'none';
      document.getElementById('wiz-logo-image-group').style.display = scene.show_logo ? 'block' : 'none';
    }
    if (scene.logo_position) { const el = document.getElementById('wiz-logo-position'); if (el) el.value = scene.logo_position; }
    if (scene.logo_image) { const el = document.getElementById('wiz-logo-image'); if (el) el.value = scene.logo_image; }

    // ===== 步骤2：默认形象（avatar.default_avatar）=====
    const avatarCfg = settings.avatar || {};
    const defaultAvatarId = avatarCfg.default_avatar || 'default';
    if (defaultAvatarId && defaultAvatarId !== 'default') {
      const targetCard = document.querySelector(`#wiz-avatar-grid .avatar-card[data-id="${defaultAvatarId}"]`);
      if (targetCard) {
        document.querySelectorAll('#wiz-avatar-grid .avatar-card').forEach(c => c.classList.remove('selected'));
        targetCard.classList.add('selected');
        document.getElementById('wiz-avatar').value = defaultAvatarId;
      }
    }

    // ===== 步骤4：默认音色（tts.default_voice）=====
    const ttsCfg = settings.tts || {};
    const defaultVoiceId = ttsCfg.default_voice;
    if (defaultVoiceId) {
      const voiceCard = document.querySelector(`#wiz-voice-grid .voice-card[data-id="${defaultVoiceId}"]`);
      if (voiceCard) {
        document.querySelectorAll('#wiz-voice-grid .voice-card').forEach(c => c.classList.remove('selected'));
        voiceCard.classList.add('selected');
        document.getElementById('wiz-voice').value = defaultVoiceId;
        // 同步 emotion 支持状态
        const evt = new Event('click');
        // 触发 updateEmotionSupport 等价逻辑
        const supports = voiceCard.dataset.supportsEmotion === '1';
        const emotionGrid = document.getElementById('wiz-emotion-grid');
        const emotionHint = document.getElementById('wiz-emotion-hint');
        if (emotionGrid) {
          emotionGrid.style.opacity = supports ? '1' : '0.4';
          emotionGrid.style.pointerEvents = supports ? 'auto' : 'none';
        }
        if (emotionHint) emotionHint.style.display = supports ? 'none' : 'block';
      }
    }

    // ===== 步骤4：音频参数（audio.speed/volume/pitch/emotion/pause/remove_silence/voice_enhance）=====
    const audio = settings.audio || {};
    if (audio.speed != null) { const el = document.getElementById('wiz-speed'); if (el) el.value = audio.speed; }
    if (audio.volume != null) { const el = document.getElementById('wiz-volume'); if (el) el.value = audio.volume; }
    if (audio.pitch != null) { const el = document.getElementById('wiz-pitch'); if (el) el.value = audio.pitch; }
    if (audio.pause_duration != null) { const el = document.getElementById('wiz-pause'); if (el) el.value = audio.pause_duration; }
    if (audio.emotion) setBtnCardValue('wiz-emotion-grid', audio.emotion);
    if (audio.remove_silence != null) { const el = document.getElementById('wiz-remove-silence'); if (el) el.checked = !!audio.remove_silence; }
    if (audio.voice_enhance != null) { const el = document.getElementById('wiz-voice-enhance'); if (el) el.checked = !!audio.voice_enhance; }

    // ===== 步骤5：BGM 设置（audio.bgm.*）=====
    const bgm = audio.bgm || {};
    if (bgm.enabled != null) {
      const el = document.getElementById('wiz-bgm-enabled'); if (el) el.checked = !!bgm.enabled;
      document.getElementById('wiz-bgm-group').style.display = bgm.enabled ? 'block' : 'none';
    }
    if (bgm.track) { const el = document.getElementById('wiz-bgm-track'); if (el) el.value = bgm.track; }
    if (bgm.volume != null) { const el = document.getElementById('wiz-bgm-vol'); if (el) el.value = bgm.volume; }
    if (bgm.fade_in != null) { const el = document.getElementById('wiz-bgm-fadein'); if (el) el.value = bgm.fade_in; }
    if (bgm.fade_out != null) { const el = document.getElementById('wiz-bgm-fadeout'); if (el) el.value = bgm.fade_out; }

    // ===== 步骤5：字幕样式（subtitle.*）=====
    const subtitle = settings.subtitle || {};
    if (subtitle.preset && window._subtitleStylePresets) {
      // 重新渲染字幕样式网格，选中配置中的 preset
      renderSubtitleStyleGrid('wiz-subtitle-style-grid', window._subtitleStylePresets, subtitle.preset, (key) => {
        wizardState.selectedSubtitleStyle = key;
        applySubtitleStylePreset(key);
      });
    }
    if (subtitle.animation) { const el = document.getElementById('wiz-sub-anim'); if (el) el.value = subtitle.animation; }
    if (subtitle.font_size != null) { const el = document.getElementById('wiz-sub-size'); if (el) el.value = subtitle.font_size; }
    if (subtitle.letter_spacing != null) { const el = document.getElementById('wiz-sub-letter'); if (el) el.value = subtitle.letter_spacing; }
    if (subtitle.dual_line != null) { const el = document.getElementById('wiz-sub-dual'); if (el) el.checked = !!subtitle.dual_line; }
    if (subtitle.karaoke != null) { const el = document.getElementById('wiz-sub-karaoke'); if (el) el.checked = !!subtitle.karaoke; }
    if (subtitle.position) { const el = document.getElementById('wiz-sub-position'); if (el) el.value = subtitle.position; }

    // ===== 步骤5：视频效果（effects.*）=====
    const effects = settings.effects || {};
    if (effects.transition) { const el = document.getElementById('wiz-transition'); if (el) el.value = effects.transition; }
    if (effects.filter) { const el = document.getElementById('wiz-filter'); if (el) el.value = effects.filter; }

    // 更新文案字数统计（emotion 变化时可能影响时长预估）
    const scriptEl = document.getElementById('wiz-script');
    if (scriptEl && scriptEl.value) updateScriptStats(scriptEl.value);

    window._wizardSettingsApplied = true;
  } catch (e) {
    console.warn('applySettingsToWizard error:', e);
  }
}

// 联动 P3：向导平台选择动态化 + 登录态校验
// 复用 settings.js 的 PLATFORM_INFO 和 _platformLoginStatus，但独立实现渲染逻辑
// 平台卡片显示登录态徽章：✓ 已登录（绿）/ ⚠ 登录失效（橙）/ ✗ 未登录（红）
const WIZ_PLATFORM_INFO = {
  bilibili: { name: '哔哩哔哩', icon: '🎬', method: 'api' },
  douyin: { name: '抖音', icon: '🎵', method: 'playwright' },
  kuaishou: { name: '快手', icon: '⚡', method: 'playwright' },
  wechat_video: { name: '微信视频号', icon: '💬', method: 'playwright' },
};
// 向导登录态缓存（独立于 settings.js 的 _platformLoginStatus，避免互相干扰）
window._wizPlatformLoginStatus = window._wizPlatformLoginStatus || {};

async function loadWizardPublishPlatforms() {
  const grid = document.getElementById('wiz-publish-platforms');
  const hintEl = document.getElementById('wiz-publish-platforms-hint');
  if (!grid) return;
  try {
    // 1. 获取 Cookie 配置状态
    const cookieResult = await api('/api/publish/cookies').catch(() => ({ cookies: {} }));
    const cookies = cookieResult.cookies || {};

    // 2. 第一阶段：基于 Cookie 文件快速渲染（已配置显示"校验中"，未配置显示"未登录"）
    grid.innerHTML = Object.entries(WIZ_PLATFORM_INFO).map(([key, info]) => {
      const c = cookies[key] || {};
      const configured = c.configured;
      // 保留用户之前勾选的状态（如果已渲染过）
      const prevCheckbox = document.querySelector(`#wiz-publish-platforms input[value="${key}"]`);
      const wasChecked = prevCheckbox ? prevCheckbox.checked : (key === 'douyin'); // 默认勾选抖音
      const statusBadge = configured
        ? '<span class="wiz-platform-badge wiz-platform-badge-pending">⏳ 校验中</span>'
        : '<span class="wiz-platform-badge wiz-platform-badge-offline">✗ 未登录</span>';
      const cardClass = configured ? 'wiz-platform-card wiz-platform-card-pending' : 'wiz-platform-card wiz-platform-card-offline';
      return `
        <label class="${cardClass}" data-platform="${key}">
          <input type="checkbox" value="${key}" ${wasChecked ? 'checked' : ''}>
          <span class="platform-checkbox-icon">${info.icon}</span>
          <span class="platform-checkbox-name">${info.name}</span>
          ${statusBadge}
        </label>
      `;
    }).join('');
    if (hintEl) hintEl.style.display = 'block';
    if (window.lucide) lucide.createIcons();

    // 3. 第二阶段：对已配置平台并行调用 login_check API 真实校验
    const configuredPlatforms = Object.entries(WIZ_PLATFORM_INFO)
      .filter(([key]) => cookies[key]?.configured)
      .map(([key]) => key);

    if (configuredPlatforms.length === 0) return;

    // 并行校验
    configuredPlatforms.forEach(async (platform) => {
      try {
        const result = await api('/api/publish/test/login_check', {
          method: 'POST',
          body: { platform },
        });
        window._wizPlatformLoginStatus[platform] = result;
        // 更新对应卡片
        updateWizPlatformCard(platform, result);
      } catch (e) {
        window._wizPlatformLoginStatus[platform] = { success: false, error: e.message };
        updateWizPlatformCard(platform, { success: false, error: e.message });
      }
    });
  } catch (e) {
    grid.innerHTML = `<div style="grid-column:1/-1;color:var(--color-error);font-size:12px;padding:8px">加载平台状态失败: ${e.message}</div>`;
  }
}

// 更新单个平台卡片的登录态徽章和样式
function updateWizPlatformCard(platform, result) {
  const card = document.querySelector(`#wiz-publish-platforms .wiz-platform-card[data-platform="${platform}"]`);
  if (!card) return;
  // 移除旧的徽章
  const oldBadge = card.querySelector('.wiz-platform-badge');
  if (oldBadge) oldBadge.remove();

  let badgeClass = 'wiz-platform-badge';
  let badgeText = '';
  let cardClass = 'wiz-platform-card';
  if (!result.success) {
    badgeClass += ' wiz-platform-badge-warning';
    badgeText = '⚠ 校验失败';
    cardClass += ' wiz-platform-card-warning';
  } else if (result.logged_in) {
    badgeClass += ' wiz-platform-badge-online';
    badgeText = '✓ 已登录';
    cardClass += ' wiz-platform-card-online';
  } else {
    badgeClass += ' wiz-platform-badge-offline';
    const reason = result.has_login_form ? 'Cookie已失效'
      : (result.upload_link_to_login ? '登录态已过期' : '未真正登录');
    badgeText = '✗ ' + reason;
    cardClass += ' wiz-platform-card-offline';
  }
  card.className = cardClass;
  card.insertAdjacentHTML('beforeend', `<span class="${badgeClass}">${badgeText}</span>`);
}

// 联动 P3：检查选中平台中是否有未登录的，返回未登录平台列表
function getWizUnloggedPlatforms() {
  const checked = Array.from(document.querySelectorAll('#wiz-publish-platforms input[type="checkbox"]:checked'));
  const unlogged = [];
  checked.forEach(cb => {
    const platform = cb.value;
    const status = window._wizPlatformLoginStatus[platform];
    // 未配置 Cookie 或登录态校验失败或登录态失效
    if (!status) {
      // 未配置 Cookie
      unlogged.push(platform);
    } else if (!status.success || !status.logged_in) {
      unlogged.push(platform);
    }
  });
  return unlogged;
}

// 联动 P3：跳转到设置中心发布页
function gotoPublishSettings() {
  if (typeof navigate === 'function') {
    navigate('settings-publish');
  } else if (window.location) {
    window.location.hash = '#settings-publish';
  }
}

// 渲染音色卡片网格
function renderWizardVoiceGrid(voices) {
  const grid = document.getElementById('wiz-voice-grid');
  if (!grid) return;
  const list = voices && voices.length ? voices : [{ voice_id: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女·温暖）', type: 'preset', provider: 'edge_tts', gender: 'female' }];
  grid.innerHTML = list.map(v => {
    const id = v.voice_id;
    const type = v.type || 'custom';
    const provider = v.provider || 'edge_tts';
    // 显示名称：优先用 label，否则用 voice_id
    const displayName = v.label || v.voice_id;
    const desc = v.description || '';
    const gender = v.gender || '';
    const genderIcon = gender === 'female' ? '👩' : (gender === 'male' ? '👨' : '🎵');
    const genderLabel = gender === 'female' ? '女声' : (gender === 'male' ? '男声' : '');
    const providerLabel = provider === 'edge_tts' ? 'Edge' : (provider === 'moss_nano' ? 'MOSS' : provider);
    const typeLabel = type === 'preset' ? '预制' : (type === 'provider_default' || type === 'default' ? '默认' : '克隆');
    const typeClass = type === 'preset' ? 'type-preset' : (type === 'provider_default' || type === 'default' ? 'type-default' : 'type-custom');
    return `
      <div class="voice-card" data-id="${id}" data-supports-emotion="${v.supports_emotion ? '1' : '0'}">
        <div class="voice-card-header">
          <div class="voice-card-info">
            <div class="voice-card-name">${genderIcon} ${displayName}</div>
            <div class="voice-card-tags">
              <span class="voice-card-tag ${typeClass}">${typeLabel}</span>
              ${genderLabel ? `<span class="voice-card-tag provider">${genderLabel}</span>` : ''}
              <span class="voice-card-tag provider-tag">${providerLabel}</span>
            </div>
            ${desc ? `<div class="voice-card-desc">${desc}</div>` : ''}
          </div>
          <button class="voice-preview-btn" data-voice="${id}" type="button" title="试听"><i data-lucide="play"></i></button>
        </div>
      </div>
    `;
  }).join('');
  if (window.lucide) lucide.createIcons();
  // 默认选中第一个
  const firstId = list[0].voice_id;
  document.getElementById('wiz-voice').value = firstId;
  // 检查音色是否支持emotion，更新emotion区域提示
  function updateEmotionSupport(card) {
    const supports = card.dataset.supportsEmotion === '1';
    const emotionGrid = document.getElementById('wiz-emotion-grid');
    const emotionHint = document.getElementById('wiz-emotion-hint');
    if (emotionGrid) {
      emotionGrid.style.opacity = supports ? '1' : '0.4';
      emotionGrid.style.pointerEvents = supports ? 'auto' : 'none';
    }
    if (emotionHint) {
      emotionHint.style.display = supports ? 'none' : 'block';
    }
  }
  grid.querySelectorAll('.voice-card').forEach(card => {
    if (card.dataset.id === firstId) {
      card.classList.add('selected');
      updateEmotionSupport(card);
    }
    card.addEventListener('click', e => {
      // 点击试听按钮不触发选中
      if (e.target.closest('.voice-preview-btn')) return;
      const isSelected = card.classList.contains('selected');
      grid.querySelectorAll('.voice-card').forEach(c => c.classList.remove('selected'));
      if (isSelected) {
        document.getElementById('wiz-voice').value = firstId;
        // 取消选中时回退到默认音色，同步更新 emotion 支持状态
        const firstCard = grid.querySelector(`.voice-card[data-id="${firstId}"]`);
        if (firstCard) updateEmotionSupport(firstCard);
      } else {
        card.classList.add('selected');
        document.getElementById('wiz-voice').value = card.dataset.id;
        updateEmotionSupport(card);
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

// 停止所有试听音频（页面/步骤切换时调用，避免后台继续播放）
function stopAllPreviewAudio() {
  // 音色试听
  if (_currentPreviewAudio && !_currentPreviewAudio.paused) {
    _currentPreviewAudio.pause();
    if (_currentPreviewBtn) {
      _currentPreviewBtn.classList.remove('playing');
      setBtnIcon(_currentPreviewBtn, 'play', '');
    }
    _currentPreviewAudio = null;
    _currentPreviewBtn = null;
  }
  // 文案试听
  if (_scriptPreviewAudio && !_scriptPreviewAudio.paused) {
    _scriptPreviewAudio.pause();
    const ttsBtn = document.getElementById('wiz-preview-tts-btn');
    if (ttsBtn) setBtnIcon(ttsBtn, 'headphones', '试听');
    _scriptPreviewAudio = null;
  }
  // BGM 试听
  if (_bgmPreviewAudio && !_bgmPreviewAudio.paused) {
    _bgmPreviewAudio.pause();
    const bgmBtn = document.getElementById('wiz-bgm-preview-btn');
    if (bgmBtn) setBtnIcon(bgmBtn, 'play', '');
    _bgmPreviewAudio = null;
  }
}

async function playVoicePreview(voiceId, btn) {
  // 如果正在播放，停止
  if (_currentPreviewAudio && !_currentPreviewAudio.paused) {
    _currentPreviewAudio.pause();
    if (_currentPreviewBtn) {
      _currentPreviewBtn.classList.remove('playing');
      setBtnIcon(_currentPreviewBtn, 'play', '');
    }
    // 如果点的是同一个按钮，仅停止
    if (_currentPreviewBtn === btn) {
      _currentPreviewAudio = null;
      _currentPreviewBtn = null;
      return;
    }
  }
  btn.classList.add('playing');
  // 加载期间显示 loading（避免点击后无反馈）
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  if (window.lucide) lucide.createIcons();
  _currentPreviewBtn = btn;
  try {
    // 直接请求预生成试听样本（内置音色即时返回，自定义音色回退实时合成）
    const audio = new Audio(`/api/voice/preview/${encodeURIComponent(voiceId)}`);
    _currentPreviewAudio = audio;
    // 音频加载完成后才切到 pause 图标
    audio.addEventListener('canplay', () => {
      setBtnIcon(btn, 'pause', '');
    });
    audio.addEventListener('ended', () => {
      btn.classList.remove('playing');
      setBtnIcon(btn, 'play', '');
      _currentPreviewAudio = null;
      _currentPreviewBtn = null;
    });
    audio.addEventListener('error', () => {
      btn.classList.remove('playing');
      setBtnIcon(btn, 'play', '');
      _currentPreviewAudio = null;
      _currentPreviewBtn = null;
      toast('音频播放失败', 'error');
    });
    await audio.play();
  } catch (e) {
    btn.classList.remove('playing');
    setBtnIcon(btn, 'play', '');
    _currentPreviewAudio = null;
    _currentPreviewBtn = null;
    toast(`试听失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
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
      warningEl.innerHTML = '<i data-lucide="alert-triangle"></i> 文案较长，生成时间可能增加';
      if (window.lucide) lucide.createIcons();
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
  const smoothBtn = document.getElementById('wiz-smooth-btn');
  if (smoothBtn) smoothBtn.addEventListener('click', () => wizardScriptQuickProcess('smooth', null));
  const hookBtn = document.getElementById('wiz-hook-btn');
  if (hookBtn) hookBtn.addEventListener('click', () => wizardScriptQuickProcess('hook', null));
  const clearBtn = document.getElementById('wiz-clear-btn');
  if (clearBtn) clearBtn.addEventListener('click', () => {
    document.getElementById('wiz-script').value = '';
    updateScriptStats('');
    wizardState.scriptProcessed = false;  // 清空后重置标记，下次生成需重新处理
    toast('已清空文案', 'info');
  });
  const analyzeBtn = document.getElementById('wiz-analyze-btn');
  if (analyzeBtn) analyzeBtn.addEventListener('click', analyzeViralScript);
  const previewTtsBtn = document.getElementById('wiz-preview-tts-btn');
  if (previewTtsBtn) previewTtsBtn.addEventListener('click', previewScriptTts);
  const viralCloseBtn = document.getElementById('wiz-viral-close');
  if (viralCloseBtn) viralCloseBtn.addEventListener('click', () => {
    document.getElementById('wiz-viral-analysis').style.display = 'none';
  });
  // 占位符填充表单按钮
  const fillBtn = document.getElementById('wiz-fill-script-btn');
  if (fillBtn) fillBtn.addEventListener('click', fillScriptTemplate);
  const hidePhBtn = document.getElementById('wiz-hide-placeholder-btn');
  if (hidePhBtn) hidePhBtn.addEventListener('click', () => {
    const form = document.getElementById('wiz-placeholder-form');
    if (form) form.style.display = 'none';
  });
}

// 文案快速 AI 处理（工具栏）
async function wizardScriptQuickProcess(action, style) {
  const script = document.getElementById('wiz-script').value.trim();
  if (!script) { toast('请先输入文案', 'error'); return; }
  const actionLabel = {polish:'润色',expand:'扩写',shorten:'缩写',smooth:'顺滑',hook:'钩子优化'}[action] || action;
  toast(`正在执行 AI ${actionLabel}...`, 'info');
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script, action, style },
    });
    if (result.success) {
      showScriptDiff(script, result.script, actionLabel, result.mock);
    } else {
      toast(`处理失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`处理失败: ${e.message}`, 'error');
  }
}

// 文案对比视图：显示原文 vs 修改后，让用户选择接受或取消
function showScriptDiff(original, modified, actionLabel, isMock) {
  const panel = document.getElementById('wiz-viral-analysis');
  const body = document.getElementById('wiz-viral-body');
  if (!panel || !body) {
    // 降级：直接替换
    document.getElementById('wiz-script').value = modified;
    updateScriptStats(modified);
    wizardState.scriptProcessed = true;
    toast(`处理成功${isMock ? '（Mock 模式）' : ''}`, 'success');
    return;
  }
  panel.style.display = 'block';
  document.querySelector('.viral-analysis-title').innerHTML = `<i data-lucide="git-compare"></i> AI${actionLabel}对比`;
  const origLines = original.split('\n');
  const modLines = modified.split('\n');
  body.innerHTML = `
    <div class="script-diff-toolbar">
      <span class="script-diff-info">原文 ${origLines.length} 行 / 修改后 ${modLines.length} 行</span>
      <div class="script-diff-actions">
        <button class="btn btn-sm btn-ghost" id="diff-cancel" type="button"><i data-lucide="x"></i> 取消</button>
        <button class="btn btn-sm btn-primary" id="diff-accept" type="button"><i data-lucide="check"></i> 接受修改</button>
      </div>
    </div>
    <div class="script-diff-grid">
      <div class="script-diff-col">
        <div class="script-diff-col-head">原文</div>
        <div class="script-diff-content">${escapeHtml(original)}</div>
      </div>
      <div class="script-diff-col">
        <div class="script-diff-col-head script-diff-modified">修改后${isMock ? '（Mock）' : ''}</div>
        <div class="script-diff-content">${escapeHtml(modified)}</div>
      </div>
    </div>`;
  lucide.createIcons();
  document.getElementById('diff-accept').addEventListener('click', () => {
    document.getElementById('wiz-script').value = modified;
    updateScriptStats(modified);
    wizardState.scriptProcessed = true;
    panel.style.display = 'none';
    toast(`已接受 AI${actionLabel}结果`, 'success');
  });
  document.getElementById('diff-cancel').addEventListener('click', () => {
    panel.style.display = 'none';
    toast('已取消修改', 'info');
  });
}

function renderWizardStepper() {
  const steps = document.querySelectorAll('.wizard-step');
  const lines = document.querySelectorAll('.wizard-step-line');
  steps.forEach((step, idx) => {
    const stepNum = parseInt(step.dataset.step);
    step.classList.remove('active', 'completed');
    if (stepNum < wizardState.currentStep && stepNum < wizardState.maxVisitedStep) {
      step.classList.add('completed');
    } else if (stepNum === wizardState.currentStep) {
      step.classList.add('active');
    }
  });
  lines.forEach((line, idx) => {
    line.classList.toggle('completed', idx + 1 < wizardState.currentStep && idx + 1 < wizardState.maxVisitedStep);
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
    setBtnIcon(nextBtn, 'rocket', '开始生成');
  } else {
    nextBtn.innerHTML = '下一步 →';
  }
  // 进入步骤6时渲染汇总
  if (wizardState.currentStep === 6) renderWizardSummary();
}

function wizardGoToStep(step) {
  if (step < 1 || step > 6) return;
  // 切换步骤前停止所有试听音频
  stopAllPreviewAudio();
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
  // 必填校验：步骤3文案必须有文案或参考链接
  if (wizardState.currentStep === 3) {
    const script = (document.getElementById('wiz-script')?.value || '').trim();
    const refUrl = (document.getElementById('wiz-ref-url')?.value || '').trim();
    if (!script && !refUrl) {
      toast('请输入文案或填写参考视频链接提取文案', 'error');
      return;
    }
  }
  // 切换步骤前停止所有试听音频
  stopAllPreviewAudio();
  wizardSaveCurrentStep();
  wizardState.currentStep++;
  wizardState.maxVisitedStep = Math.max(wizardState.maxVisitedStep, wizardState.currentStep);
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
    logo_image: document.getElementById('wiz-logo-image')?.value || '',
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
  const preset = wizardState.selectedSubtitleStyle || 'douyin_hot';
  // 从预设读取颜色相关字段，确保切换预设时颜色同步保存（向导UI无独立颜色控件，颜色由预设决定）
  const styleInfo = (_creativePresets && _creativePresets.subtitle_styles && _creativePresets.subtitle_styles[preset]) || {};
  return {
    preset: preset,
    animation: document.getElementById('wiz-sub-anim').value,
    position: document.getElementById('wiz-sub-position').value,
    font_size: parseInt(document.getElementById('wiz-sub-size').value),
    letter_spacing: parseInt(document.getElementById('wiz-sub-letter').value),
    dual_line: document.getElementById('wiz-sub-dual').checked,
    karaoke: document.getElementById('wiz-sub-karaoke').checked,
    // 颜色字段：从字幕样式预设带入，与后端 apply_template 逻辑一致
    primary_color: styleInfo.primary_color,
    outline_color: styleInfo.outline_color,
    outline_width: styleInfo.outline_width,
    shadow_color: styleInfo.shadow_color,
    bold: styleInfo.bold,
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
        // 保存已应用的模板对象，供步骤切换时重新回显（防止 DOM 时序问题导致值丢失）
        wizardState.appliedTemplate = tpl;
        if (_creativePresets) {
          // 情感
          setBtnCardValue('wiz-emotion-grid', tpl.emotion);
          // 字幕动画
          const animSel = document.getElementById('wiz-sub-anim');
          if (animSel) animSel.value = tpl.subtitle_animation;
          // 转场（确保 option 存在再设值，避免 select 静默拒绝）
          const transSel = document.getElementById('wiz-transition');
          if (transSel) {
            if (tpl.transition && !Array.from(transSel.options).some(o => o.value === tpl.transition)) {
              const opt = document.createElement('option');
              opt.value = tpl.transition;
              opt.textContent = tpl.transition;
              transSel.appendChild(opt);
            }
            transSel.value = tpl.transition;
          }
          // 滤镜
          const filterSel = document.getElementById('wiz-filter');
          if (filterSel) {
            if (tpl.filter && !Array.from(filterSel.options).some(o => o.value === tpl.filter)) {
              const opt = document.createElement('option');
              opt.value = tpl.filter;
              opt.textContent = tpl.filter;
              filterSel.appendChild(opt);
            }
            filterSel.value = tpl.filter;
          }
          // BGM
          const bgmSel = document.getElementById('wiz-bgm-track');
          if (bgmSel) bgmSel.value = tpl.bgm_track;
          // 高亮字幕样式卡片（若预设不在列表中，回退到 minimal_white 避免空高亮）
          const subPresets = _creativePresets.subtitle_styles || {};
          const subKey = subPresets[tpl.subtitle_preset] ? tpl.subtitle_preset : 'minimal_white';
          renderSubtitleStyleGrid('wiz-subtitle-style-grid', subPresets, subKey, (k) => {
            wizardState.selectedSubtitleStyle = k;
          });
          // 启用 BGM
          document.getElementById('wiz-bgm-enabled').checked = true;
          document.getElementById('wiz-bgm-group').style.display = 'block';

          // 语速联动
          if (tpl.speech_speed) {
            const speedEl = document.getElementById('wiz-speed');
            const speedVal = document.getElementById('wiz-speed-val');
            if (speedEl) {
              speedEl.value = tpl.speech_speed;
              if (speedVal) speedVal.textContent = tpl.speech_speed + 'x';
            }
          }

          // 音色联动
          if (tpl.voice) {
            const voiceHidden = document.getElementById('wiz-voice');
            if (voiceHidden) voiceHidden.value = tpl.voice;
            // 高亮音色卡片
            document.querySelectorAll('#wiz-voice-grid .voice-card').forEach(c => c.classList.remove('selected'));
            const voiceCard = document.querySelector(`#wiz-voice-grid .voice-card[data-id="${tpl.voice}"]`);
            if (voiceCard) voiceCard.classList.add('selected');
          }

          // 数字人形象联动
          if (tpl.avatar) {
            const avatarHidden = document.getElementById('wiz-avatar');
            if (avatarHidden) avatarHidden.value = tpl.avatar;
            // 高亮形象卡片
            document.querySelectorAll('#wiz-avatar-grid .avatar-card').forEach(c => c.classList.remove('selected'));
            const avatarCard = document.querySelector(`#wiz-avatar-grid .avatar-card[data-id="${tpl.avatar}"]`);
            if (avatarCard) avatarCard.classList.add('selected');
          }

          // 数字人场景联动（位置/大小/背景）：tpl.avatar_scene → 步骤2 场景配置 UI
          // 注意：模板字段值与向导 UI 值存在差异，需要映射
          //   position: bottom_right→right, bottom_left→left, center→center, top_*→center
          //   background_type: color→solid, transparent/image 保持
          //   pose: talking 等不在向导可选值内，跳过（向导 pose 是 standing/sitting/half_body/closeup）
          if (tpl.avatar_scene) {
            const ascene = tpl.avatar_scene;
            // 位置
            if (ascene.position) {
              const posMap = { bottom_right: 'right', bottom_left: 'left', top_right: 'center', top_left: 'center', center: 'center' };
              const posVal = posMap[ascene.position] || ascene.position;
              setBtnCardValue('wiz-position-grid', posVal);
            }
            // 大小
            if (ascene.scale != null) {
              const scaleEl = document.getElementById('wiz-scale');
              const scaleValEl = document.getElementById('wiz-scale-val');
              if (scaleEl) {
                scaleEl.value = ascene.scale;
                if (scaleValEl) scaleValEl.textContent = ascene.scale;
              }
            }
            // 背景类型
            if (ascene.background_type) {
              const bgTypeMap = { color: 'solid', solid: 'solid', image: 'image', transparent: 'transparent' };
              const bgTypeVal = bgTypeMap[ascene.background_type] || ascene.background_type;
              setBtnCardValue('wiz-bg-type-grid', bgTypeVal);
              const bgGroup = document.getElementById('wiz-bg-color-group');
              const imgGroup = document.getElementById('wiz-bg-image-group');
              if (bgGroup) bgGroup.style.display = bgTypeVal === 'solid' ? 'block' : 'none';
              if (imgGroup) imgGroup.style.display = bgTypeVal === 'image' ? 'block' : 'none';
            }
            // 背景颜色
            if (ascene.background_color) {
              const bgColEl = document.getElementById('wiz-bg-color');
              if (bgColEl) bgColEl.value = ascene.background_color;
            }
          }

          // 文案骨架联动：渲染占位符填充表单 + 填入骨架原文（用户可二选一）
          wizardState.selectedTemplateObj = tpl;  // 供 fillScriptTemplate 使用
          renderPlaceholderForm(tpl);
          if (tpl.script_template) {
            const scriptEl = document.getElementById('wiz-script');
            if (scriptEl && !scriptEl.value.trim()) {
              // 仅在文案为空时填入骨架，避免覆盖用户已输入的内容
              scriptEl.value = tpl.script_template.trim();
              // 触发字数统计更新
              if (typeof updateScriptStats === 'function') updateScriptStats(tpl.script_template.trim());
            }
          }

          toast(`已应用「${tpl.label}」全套配置：字幕/${tpl.subtitle_preset} · 滤镜/${tpl.filter} · 转场/${tpl.transition} · 音色/${tpl.voice || '默认'} · 语速/${tpl.speech_speed || 1.0}x`, 'success');
        }
      }
    } else {
      toast(result.message || '应用失败', 'error');
    }
  } catch (e) {
    toast(`应用模板失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    setBtnIcon(btn, 'check', '应用此模板');
  }
}

// 渲染模板占位符填充表单：根据 tpl.placeholders 动态生成输入字段
// 用户填值后点击"生成完整文案"按钮，调用 fillScriptTemplate() 替换骨架中的占位符
function renderPlaceholderForm(tpl) {
  const formEl = document.getElementById('wiz-placeholder-form');
  const fieldsEl = document.getElementById('wiz-placeholder-fields');
  if (!formEl || !fieldsEl) return;

  // 清空旧字段
  fieldsEl.innerHTML = '';

  const placeholders = tpl && tpl.placeholders ? tpl.placeholders : {};
  const keys = Object.keys(placeholders);
  if (!tpl || !tpl.script_template || keys.length === 0) {
    // 模板无占位符：隐藏表单
    formEl.style.display = 'none';
    return;
  }

  // 渲染输入字段（每个占位符一个 input）
  keys.forEach((key) => {
    const hint = placeholders[key] || '';
    const wrapper = document.createElement('div');
    wrapper.className = 'ph-field';
    wrapper.innerHTML = `
      <label>{${key}}</label>
      <input type="text" data-ph-key="${key}" placeholder="${hint.replace(/"/g, '&quot;')}" />
    `;
    fieldsEl.appendChild(wrapper);
  });

  formEl.style.display = 'block';
  // 重新渲染 lucide 图标
  if (window.lucide) window.lucide.createIcons();
}

// 根据用户填入的占位符值，替换 tpl.script_template 中的 {key}，生成完整文案
function fillScriptTemplate() {
  const tpl = wizardState.selectedTemplateObj;
  if (!tpl || !tpl.script_template) {
    toast('请先选择并应用一个模板', 'error');
    return;
  }
  const fieldsEl = document.getElementById('wiz-placeholder-fields');
  if (!fieldsEl) return;

  // 收集用户填入的值
  const inputs = fieldsEl.querySelectorAll('input[data-ph-key]');
  const values = {};
  let missing = 0;
  inputs.forEach((inp) => {
    const k = inp.dataset.phKey;
    const v = (inp.value || '').trim();
    values[k] = v;
    if (!v) missing += 1;
  });

  if (missing > 0) {
    if (!confirm(`还有 ${missing} 个占位符未填写，未填写的将保留为 {字段名}。是否继续生成？`)) return;
  }

  // 替换骨架中的 {key}（支持 key 含字母数字下划线）
  let filled = tpl.script_template;
  Object.keys(values).forEach((k) => {
    if (values[k]) {
      // 用正则替换 {key}（防止 $ 在替换串中被特殊解析）
      filled = filled.replace(new RegExp('\\{' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\}', 'g'), values[k]);
    }
  });
  filled = filled.trim();

  // 写入文案输入框并触发统计更新
  const scriptEl = document.getElementById('wiz-script');
  if (scriptEl) {
    scriptEl.value = filled;
    if (typeof updateScriptStats === 'function') updateScriptStats(filled);
  }
  toast(`已生成完整文案（${filled.length} 字）`, 'success');
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
  // 获取当前选中的爆款模板 ID
  const activeTpl = document.querySelector('#wiz-template-grid .template-card.active');
  const templateId = activeTpl ? activeTpl.dataset.tplid || '' : '';
  const btn = document.getElementById('wiz-ai-generate-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 生成中...';
  try {
    const body = { script: topic, action: 'generate', style, topic };
    if (templateId) body.template_id = templateId;
    const result = await api('/api/script/process', {
      method: 'POST',
      body,
    });
    if (result.success) {
      document.getElementById('wiz-script').value = result.script;
      updateScriptStats(result.script);
      // 标记文案已处理：AI生成的文案不需要再 polish
      wizardState.scriptProcessed = true;
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
    setBtnIcon(btn, 'lightbulb', '生成文案');
  }
}

// 加载文案爆款模板库并渲染卡片网格
async function loadScriptTemplates() {
  const grid = document.getElementById('wiz-template-grid');
  if (!grid) return;
  try {
    const result = await api('/api/script/templates', { method: 'GET' });
    if (!result.success || !Array.isArray(result.templates)) return;
    // 保留首张"自由创作"卡片，在其后追加模板卡片
    const freeCard = grid.querySelector('.template-card[data-tplid=""]');
    grid.innerHTML = '';
    if (freeCard) grid.appendChild(freeCard);
    result.templates.forEach(tpl => {
      const card = document.createElement('div');
      card.className = 'template-card';
      card.dataset.tplid = tpl.id;
      card.innerHTML = `
        <i data-lucide="${tpl.icon || 'file-text'}"></i>
        <span class="tpl-name">${tpl.name}</span>
        <span class="tpl-desc">${tpl.desc || ''}</span>
      `;
      card.addEventListener('click', () => selectScriptTemplate(card, tpl));
      grid.appendChild(card);
    });
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    // 静默失败：模板不可用时仍可用自由创作
  }
}

function selectScriptTemplate(card, tpl) {
  // 切换选中态
  document.querySelectorAll('#wiz-template-grid .template-card').forEach(c => c.classList.remove('active'));
  card.classList.add('active');
  // 显示模板结构提示
  const hint = document.getElementById('wiz-tpl-hint');
  if (hint) {
    hint.style.display = 'block';
    hint.innerHTML = `<strong>${tpl.name}：</strong>${tpl.structure}`;
  }
}

// ============ 封面样式选择与预览 ============

let _coverSelectedStyle = 'deep_blue';
let _coverPreviewTimer = null;

// 加载封面样式预设列表
async function loadCoverStyles() {
  const grid = document.getElementById('cover-style-grid');
  if (!grid) return;
  try {
    const result = await api('/api/cover/styles', { method: 'GET' });
    if (!result.success || !Array.isArray(result.styles)) return;
    grid.innerHTML = '';
    result.styles.forEach(s => {
      const card = document.createElement('div');
      card.className = 'cover-style-card' + (s.id === _coverSelectedStyle ? ' active' : '');
      card.dataset.styleid = s.id;
      card.innerHTML = `
        <i data-lucide="${s.icon || 'palette'}"></i>
        <span class="cs-name">${s.name}</span>
        <span class="cs-desc">${s.desc || ''}</span>
      `;
      card.addEventListener('click', () => selectCoverStyle(card, s));
      grid.appendChild(card);
    });
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    // 静默失败
  }
}

function selectCoverStyle(card, style) {
  document.querySelectorAll('#cover-style-grid .cover-style-card').forEach(c => c.classList.remove('active'));
  card.classList.add('active');
  _coverSelectedStyle = style.id;
  // 触发预览（防抖）
  clearTimeout(_coverPreviewTimer);
  _coverPreviewTimer = setTimeout(generateCoverPreview, 500);
}

// 生成封面预览
async function generateCoverPreview() {
  const titleInput = document.getElementById('cover-preview-title');
  const wrapper = document.getElementById('cover-preview-wrapper');
  const img = document.getElementById('cover-preview-img');
  const btn = document.getElementById('cover-regenerate-btn');
  if (!titleInput || !wrapper || !img) return;
  const title = titleInput.value.trim();
  if (!title) { wrapper.style.display = 'none'; return; }
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 生成中...'; }
  try {
    const result = await api('/api/cover/preview', {
      method: 'POST',
      body: { title, style_id: _coverSelectedStyle },
    });
    if (result.success && result.cover_path) {
      img.src = `/api/files?path=${encodeURIComponent(result.cover_path)}&_t=${Date.now()}`;
      wrapper.style.display = 'block';
    }
  } catch (e) {
    // 静默失败
  } finally {
    if (btn) { btn.disabled = false; if (window.lucide) lucide.createIcons(); btn.innerHTML = '<i data-lucide="refresh-cw"></i> 重新生成'; if (window.lucide) lucide.createIcons(); }
  }
}

// 文案提取：分享文本实时解析预览（防抖 300ms）
let _shareTextParseTimer = null;
function bindShareTextPreview() {
  const el = document.getElementById('wiz-ref-url');
  if (!el) return;
  el.addEventListener('input', () => {
    clearTimeout(_shareTextParseTimer);
    _shareTextParseTimer = setTimeout(previewShareText, 300);
  });
}

async function previewShareText() {
  const inputEl = document.getElementById('wiz-ref-url');
  const text = inputEl.value.trim();
  const previewBox = document.getElementById('wiz-extract-preview');
  const urlEl = document.getElementById('wiz-preview-url');
  const descEl = document.getElementById('wiz-preview-desc');
  if (!previewBox) return;
  if (!text) { previewBox.style.display = 'none'; setFieldError(inputEl, ''); return; }
  try {
    const result = await api('/api/script/parse', { method: 'POST', body: { text } });
    if (result.success && (result.url || result.desc)) {
      setFieldSuccess(inputEl);
      urlEl.textContent = result.url || '—';
      descEl.textContent = result.desc || '—';
      previewBox.style.display = 'block';
    } else {
      previewBox.style.display = 'none';
    }
  } catch (e) {
    // 预览失败静默，不影响主流程
    previewBox.style.display = 'none';
  }
}

async function wizardExtractScript() {
  const refInput = document.getElementById('wiz-ref-url');
  const refUrl = refInput.value.trim();
  if (!refUrl) { setFieldError(refInput, '请输入参考视频链接'); toast('请输入参考视频链接', 'error'); return; }
  setFieldSuccess(refInput);
  const btn = document.getElementById('wiz-extract-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 提取中（约3-5分钟）...';
  // 提取文案耗时较长（下载视频+ASR转写），增加计时提示避免用户以为卡住
  const _extractStart = Date.now();
  const _extractTimer = setInterval(() => {
    if (btn.disabled) {
      const _elapsed = Math.floor((Date.now() - _extractStart) / 1000);
      const _mins = Math.floor(_elapsed / 60);
      const _secs = _elapsed % 60;
      btn.innerHTML = `<span class="spinner"></span> 提取中（${_mins}分${_secs.toString().padStart(2,'0')}秒 / 约3-5分钟）...`;
    } else {
      clearInterval(_extractTimer);
    }
  }, 1000);
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script: '', action: 'extract', topic: null, style: null, reference_url: refUrl },
    });
    if (result.success) {
      document.getElementById('wiz-script').value = result.script;
      updateScriptStats(result.script);
      // 标记文案已处理：生成视频时跳过重复的 script_extract 和 script_write
      wizardState.scriptProcessed = true;
      // 提取成功后自动切换到"手动输入"标签页，让用户看到提取的文案
      switchWizardScriptTab('manual');
      if (result.mock) {
        toast('文案提取成功（Mock 模式：未配置 ASR，返回示例文案。配置 MiMo ASR 可提取真实文案）', 'success');
      } else if (result.degraded) {
        toast('已提取文案描述（字幕暂不可用，如需完整文案可直接编辑）', 'info');
      } else {
        toast('文案提取成功', 'success');
      }
    } else {
      toast(`提取失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`提取失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    clearInterval(_extractTimer);
    setBtnIcon(btn, 'link', '提取文案');
  }
}

// 切换 wizard 步骤3 的子标签页（manual/ai/extract）
function switchWizardScriptTab(tabName) {
  // 切换子标签时停止所有试听音频
  stopAllPreviewAudio();
  document.querySelectorAll('[data-wiztab]').forEach(t => {
    t.classList.toggle('active', t.dataset.wiztab === tabName);
  });
  document.querySelectorAll('.sub-page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(`wiz-script-${tabName}`);
  if (target) target.classList.add('active');
}

// 文案试听：合成并播放文案片段
let _scriptPreviewAudio = null;
async function previewScriptTts() {
  const textarea = document.getElementById('wiz-script');
  const script = textarea.value.trim();
  if (!script) { toast('请先输入文案', 'error'); return; }
  // 优先使用选中文本，否则用前 200 字
  const selected = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd).trim();
  const text = selected || script;
  const voiceId = document.getElementById('wiz-avatar')?.value || 'default';
  // 采集当前语音设置（向导步骤4的滑块，若存在）
  const speedEl = document.getElementById('wiz-speed');
  const volumeEl = document.getElementById('wiz-volume');
  const pitchEl = document.getElementById('wiz-pitch');
  const emotionVal = typeof getBtnCardValue === 'function'
    ? (getBtnCardValue('wiz-emotion-grid') || 'neutral') : 'neutral';
  const audioBody = { text, voice_id: voiceId };
  if (speedEl) audioBody.speed = parseFloat(speedEl.value);
  if (volumeEl) audioBody.volume = parseInt(volumeEl.value);
  if (pitchEl) audioBody.pitch = parseInt(pitchEl.value);
  audioBody.emotion = emotionVal;
  // 复用全局音频控制器
  if (_scriptPreviewAudio && !_scriptPreviewAudio.paused) {
    _scriptPreviewAudio.pause();
    _scriptPreviewAudio = null;
    setBtnIcon(document.getElementById('wiz-preview-tts-btn'), 'headphones', '试听');
    return;
  }
  const btn = document.getElementById('wiz-preview-tts-btn');
  btn.disabled = true;
  // 使用 .spinner 旋转动画（与其他长时任务一致），避免静态 loader 图标看似卡住
  btn.innerHTML = '<span class="spinner"></span> 合成中...';
  if (window.lucide) lucide.createIcons();
  toast('正在合成语音，请稍候...', 'info');
  try {
    const result = await api('/api/preview/tts', {
      method: 'POST',
      body: audioBody,
    });
    if (result.success && result.audio_path) {
      const audio = new Audio(`/api/files?path=${encodeURIComponent(result.audio_path)}`);
      _scriptPreviewAudio = audio;
      // 音频加载期间也显示 loading（避免音频加载慢时看似卡住）
      btn.innerHTML = '<span class="spinner"></span> 加载中...';
      audio.addEventListener('canplay', () => {
        setBtnIcon(btn, 'pause', '停止');
      });
      audio.addEventListener('ended', () => {
        _scriptPreviewAudio = null;
        setBtnIcon(btn, 'headphones', '试听');
      });
      audio.addEventListener('error', () => {
        _scriptPreviewAudio = null;
        setBtnIcon(btn, 'headphones', '试听');
        toast('音频播放失败', 'error');
      });
      await audio.play();
      toast(`试听播放中${selected ? '（选中文本）' : '（前' + Math.min(200, script.length) + '字）'}，时长 ${result.duration}s`, 'info');
    } else {
      toast(`试听失败: ${result.error}`, 'error');
    }
  } catch (e) {
    toast(`试听失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    if (!_scriptPreviewAudio) setBtnIcon(btn, 'headphones', '试听');
  }
}

// 爆款结构分析
async function analyzeViralScript() {
  const script = document.getElementById('wiz-script').value.trim();
  if (!script) { toast('请先输入文案', 'error'); return; }
  const btn = document.getElementById('wiz-analyze-btn');
  const panel = document.getElementById('wiz-viral-analysis');
  const body = document.getElementById('wiz-viral-body');
  btn.disabled = true;
  setBtnIcon(btn, 'loader', '分析中...');
  body.innerHTML = '<div class="viral-loading"><span class="spinner"></span> 正在分析爆款结构...</div>';
  panel.style.display = 'block';
  try {
    const result = await api('/api/script/process', {
      method: 'POST',
      body: { script, action: 'analyze' },
    });
    if (result.success && result.report) {
      renderViralReport(result.report, result.mock);
    } else {
      body.innerHTML = `<div class="viral-error"><i data-lucide="alert-circle"></i> ${escapeHtml(result.error || '分析失败')}</div>`;
      lucide.createIcons();
    }
  } catch (e) {
    body.innerHTML = `<div class="viral-error"><i data-lucide="alert-circle"></i> ${escapeHtml(e.message)}</div>`;
    lucide.createIcons();
  } finally {
    btn.disabled = false;
    setBtnIcon(btn, 'search-analytics', '爆款分析');
  }
}

// 渲染爆款分析报告
function renderViralReport(report, isMock) {
  const body = document.getElementById('wiz-viral-body');
  const score = report.viral_score || 0;
  const scoreColor = score >= 75 ? '#10b981' : score >= 50 ? '#f59e0b' : '#ef4444';
  const scoreLabel = score >= 75 ? '爆款潜力高' : score >= 50 ? '有潜力，需优化' : '爆款潜力低';

  let html = '';
  if (isMock) html += '<div class="viral-mock-hint">（Mock 模式：分析结果为模板，配置 LLM 后获取真实分析）</div>';

  // 爆款分数
  html += `<div class="viral-score-section">
    <div class="viral-score-ring" style="--score-color:${scoreColor}">
      <span class="viral-score-num">${score}</span>
      <span class="viral-score-label">${scoreLabel}</span>
    </div>
    <div class="viral-score-meta">
      <div class="viral-meta-row"><span class="viral-meta-label">钩子类型</span><span class="viral-meta-value">${escapeHtml(report.hook_type || '—')}</span></div>
      <div class="viral-meta-row"><span class="viral-meta-label">情绪曲线</span><span class="viral-meta-value">${escapeHtml(report.emotion_curve || '—')}</span></div>
    </div>
  </div>`;

  // 钩子分析
  if (report.hook_analysis) {
    html += `<div class="viral-section"><div class="viral-section-title"><i data-lucide="anchor"></i> 钩子分析</div><p class="viral-section-text">${escapeHtml(report.hook_analysis)}</p></div>`;
  }

  // 结构拆解
  if (report.structure && report.structure.length > 0) {
    html += '<div class="viral-section"><div class="viral-section-title"><i data-lucide="layers"></i> 结构拆解</div><div class="viral-structure-list">';
    report.structure.forEach(s => {
      html += `<div class="viral-structure-item">
        <span class="viral-structure-tag">${escapeHtml(s.part || '')}</span>
        <span class="viral-structure-content">${escapeHtml(s.content || '')}</span>
        <span class="viral-structure-effect">${escapeHtml(s.effect || '')}</span>
      </div>`;
    });
    html += '</div></div>';
  }

  // 亮点 & 不足
  const highlights = report.highlights || [];
  const weaknesses = report.weaknesses || [];
  if (highlights.length || weaknesses.length) {
    html += '<div class="viral-section"><div class="viral-section-title"><i data-lucide="scale"></i> 亮点与不足</div><div class="viral-sw-grid">';
    if (highlights.length) {
      html += '<div class="viral-sw-col viral-highlights"><div class="viral-sw-head">亮点</div>';
      highlights.forEach(h => html += `<div class="viral-sw-item"><i data-lucide="check-circle"></i> ${escapeHtml(h)}</div>`);
      html += '</div>';
    }
    if (weaknesses.length) {
      html += '<div class="viral-sw-col viral-weaknesses"><div class="viral-sw-head">不足</div>';
      weaknesses.forEach(w => html += `<div class="viral-sw-item"><i data-lucide="x-circle"></i> ${escapeHtml(w)}</div>`);
      html += '</div>';
    }
    html += '</div></div>';
  }

  // 改进建议
  if (report.improvement) {
    html += `<div class="viral-section"><div class="viral-section-title"><i data-lucide="lightbulb"></i> 改进建议</div><p class="viral-section-text">${escapeHtml(report.improvement)}</p></div>`;
  }

  // 仿写方向 + 一键仿写按钮
  if (report.rewrite_direction) {
    html += `<div class="viral-rewrite-section">
      <div class="viral-section-title"><i data-lucide="refresh-cw"></i> 仿写方向</div>
      <p class="viral-section-text">${escapeHtml(report.rewrite_direction)}</p>
      <button class="btn btn-primary btn-sm" id="wiz-viral-rewrite" type="button"><i data-lucide="wand-2"></i> 基于分析一键仿写</button>
    </div>`;
  }

  body.innerHTML = html;
  lucide.createIcons();

  // 绑定一键仿写
  const rewriteBtn = document.getElementById('wiz-viral-rewrite');
  if (rewriteBtn) {
    rewriteBtn.addEventListener('click', async () => {
      rewriteBtn.disabled = true;
      rewriteBtn.innerHTML = '<span class="spinner"></span> 仿写中...';
      const script = document.getElementById('wiz-script').value.trim();
      try {
        const result = await api('/api/script/process', {
          method: 'POST',
          body: { script, action: 'rewrite' },
        });
        if (result.success) {
          document.getElementById('wiz-script').value = result.script;
          updateScriptStats(result.script);
          document.getElementById('wiz-viral-analysis').style.display = 'none';
          toast('仿写完成，已替换文案', 'success');
        } else {
          toast(`仿写失败: ${result.error}`, 'error');
        }
      } catch (e) {
        toast(`仿写失败: ${e.message}`, 'error');
      } finally {
        rewriteBtn.disabled = false;
        rewriteBtn.innerHTML = '<i data-lucide="wand-2"></i> 基于分析一键仿写';
        lucide.createIcons();
      }
    });
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
      updateScriptStats(result.script);
      // 标记文案已处理：生成视频时跳过重复的 script_extract 和 script_write
      wizardState.scriptProcessed = true;
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
    setBtnIcon(btn, 'play', '执行 AI 处理');
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
      <div class="summary-card-title"><i data-lucide="newspaper"></i> 模板</div>
      <div class="summary-card-row"><span class="key">模板</span><span class="val">${tplLabel}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title"><i data-lucide="user-round"></i> 数字人形象</div>
      <div class="summary-card-row"><span class="key">形象</span><span class="val">${avatar}</span></div>
      <div class="summary-card-row"><span class="key">姿态</span><span class="val">${scene.pose}</span></div>
      <div class="summary-card-row"><span class="key">位置</span><span class="val">${scene.position}</span></div>
      <div class="summary-card-row"><span class="key">大小</span><span class="val">${scene.scale}</span></div>
      <div class="summary-card-row"><span class="key">背景</span><span class="val">${scene.background_type}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title"><i data-lucide="pen-line"></i> 文案</div>
      <div class="summary-card-row"><span class="key">字数</span><span class="val">${script.length} 字</span></div>
      <div class="summary-card-row"><span class="key">预览</span><span class="val">${script.substring(0, 40)}${script.length > 40 ? '...' : ''}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title"><i data-lucide="mic"></i> 声音</div>
      <div class="summary-card-row"><span class="key">音色</span><span class="val">${voice}</span></div>
      <div class="summary-card-row"><span class="key">语速</span><span class="val">${audio.speed}</span></div>
      <div class="summary-card-row"><span class="key">音量</span><span class="val">${audio.volume}</span></div>
      <div class="summary-card-row"><span class="key">情感</span><span class="val">${audio.emotion}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title"><i data-lucide="message-square"></i> 字幕</div>
      <div class="summary-card-row"><span class="key">预设</span><span class="val">${subtitle.preset}</span></div>
      <div class="summary-card-row"><span class="key">动画</span><span class="val">${subtitle.animation}</span></div>
      <div class="summary-card-row"><span class="key">位置</span><span class="val">${subtitle.position}</span></div>
      <div class="summary-card-row"><span class="key">双行</span><span class="val">${subtitle.dual_line ? '是' : '否'}</span></div>
      <div class="summary-card-row"><span class="key">卡拉OK</span><span class="val">${subtitle.karaoke ? '是' : '否'}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title"><i data-lucide="music"></i> BGM</div>
      <div class="summary-card-row"><span class="key">启用</span><span class="val">${audio.bgm.enabled ? '是' : '否'}</span></div>
      <div class="summary-card-row"><span class="key">曲目</span><span class="val">${audio.bgm.track}</span></div>
      <div class="summary-card-row"><span class="key">音量</span><span class="val">${audio.bgm.volume}</span></div>
    </div>
    <div class="summary-card">
      <div class="summary-card-title"><i data-lucide="film"></i> 效果</div>
      <div class="summary-card-row"><span class="key">转场</span><span class="val">${effects.transition}</span></div>
      <div class="summary-card-row"><span class="key">滤镜</span><span class="val">${effects.filter}</span></div>
      <div class="summary-card-row"><span class="key">水印</span><span class="val">${effects.watermark.enabled ? '是' : '否'}</span></div>
    </div>
  `;
  if (window.lucide) lucide.createIcons();
}

// ========== 异步任务轮询（实时进度） ==========

let _progressTimerId = null;

async function pollGenerateJob(payload) {
  // 1. 异步提交任务，立即获得 job_id
  const submitResp = await api('/api/generate/async', { method: 'POST', body: payload });
  const jobId = submitResp.job_id;
  if (!jobId) throw new Error('任务提交失败：未返回 job_id');
  return _pollJobLoop(jobId);
}

// 重跑当前任务（断点续跑）：从失败/卡住的步骤恢复，无需从头开始
async function rerunCurrentJob() {
  if (!_currentJobId) {
    toast('未找到可重跑的任务', 'error');
    return;
  }
  const jobId = _currentJobId;
  const btn = document.getElementById('wiz-generate-btn');
  try {
    toast('正在重跑任务（断点续跑，从失败步骤恢复）...', 'info');
    const resp = await api(`/api/jobs/${jobId}/rerun/async`, { method: 'POST' });
    if (!resp.job_id) throw new Error('重跑请求失败');
    // 重置模态框 UI 并重新轮询
    document.getElementById('progress-modal-result').style.display = 'none';
    document.getElementById('progress-modal-close').style.display = 'none';
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 重跑中...'; }
    showProgressModal();
    document.getElementById('progress-modal-title').textContent = '正在重跑视频（断点续跑）...';
    const result = await _pollJobLoop(jobId);
    _displayWizardResult(result);
    toast(result.success ? '视频生成成功！' : '生成未完全成功', result.success ? 'success' : 'error');
  } catch (e) {
    let errMsg = e.message || '重跑失败';
    toast(`重跑失败: ${errMsg}`, 'error');
    console.error(e);
    finishProgressModalError(errMsg);
  } finally {
    if (btn) { btn.disabled = false; setBtnIcon(btn, 'rocket', '开始生成视频'); }
  }
}

// 在向导结果区展示生成结果
function _displayWizardResult(result) {
  const output = result.output || {};
  const videoPath = output.final_video || result.video_path;
  const videoAbsPath = output.final_video_absolute || videoPath;
  const title = output.title || result.title || '';
  const scriptText = output.script_text || result.script_text || '';
  const videoEl = document.getElementById('wiz-result-video');
  if (videoPath) {
    const downloadName = (title || 'video').replace(/[^\w\u4e00-\u9fa5]/g, '_').slice(0, 30) + '.mp4';
    videoEl.innerHTML = `
      <video src="/api/files?path=${encodeURIComponent(videoPath)}" controls autoplay></video>
      <div style="margin-top:8px;display:flex;gap:8px">
        <a class="btn btn-sm btn-primary" href="/api/files?path=${encodeURIComponent(videoPath)}" download="${downloadName}">
          <i data-lucide="download"></i> 下载视频
        </a>
        <button class="btn btn-sm btn-secondary" onclick="copyToClipboard('${videoAbsPath.replace(/\\/g, '\\\\')}')">
          <i data-lucide="copy"></i> 复制路径
        </button>
        ${_currentJobId ? `<button class="btn btn-sm btn-secondary" onclick="openJobFolder('${_currentJobId}')"><i data-lucide="folder-open"></i> 打开目录</button>` : ''}
      </div>
    `;
    if (window.lucide) lucide.createIcons();
  } else {
    videoEl.innerHTML = '<div class="result-video-placeholder">视频未生成</div>';
  }
  document.getElementById('wiz-result-title').textContent = title || '—';
  document.getElementById('wiz-result-script').textContent = scriptText || '—';
}

// 轮询任务状态（提交新任务和重跑共用）
async function _pollJobLoop(jobId) {
  // 重置全局跟踪状态
  _currentJobId = jobId;
  _currentRunningStep = null;
  _lastProgressTime = Date.now();
  _tierAlerts = { avatar_enter: false, min30: false, min60: false, stale: false };

  // 启动已用时计时器（每秒更新，显示当前步骤名）
  if (_progressTimerId) clearInterval(_progressTimerId);
  _progressTimerId = setInterval(() => {
    const elapsed = Math.floor((Date.now() - _progressStartTime) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    const etaEl = document.getElementById('progress-eta');
    if (etaEl && !etaEl.textContent.includes('已完成') && !etaEl.textContent.includes('失败')) {
      const stepName = _currentRunningStep ? (STEP_INFO[_currentRunningStep]?.name || _currentRunningStep) : '初始化';
      etaEl.textContent = `已用时 ${m}分${s}秒 · 正在执行：${stepName}`;
    }
  }, 1000);

  // 轮询任务状态
  const wizPipeline = document.getElementById('wiz-pipeline');
  // 最长等待 180 分钟（Wav2Lip GPU 模式约 20-30 分钟，CPU 模式长文案可达 90-120 分钟，留充足余量）
  const maxWait = 10800000;
  const pollInterval = 1500;
  const t0 = Date.now();
  let lastUpdatedAt = 0;  // 跟踪后端 updated_at，判断任务是否还在推进

  while (true) {
    if (Date.now() - t0 > maxWait) {
      throw new Error('生成超时（超过 180 分钟）。任务可能仍在后台运行，可在"任务"页面查看状态；'
        + '如需加速，建议减少文案长度、在设置中切换 resize_factor=2 快速模式，或使用 GPU 服务器');
    }
    await new Promise(r => setTimeout(r, pollInterval));

    let job;
    try {
      job = await api(`/api/jobs/${jobId}`);
    } catch (e) {
      // 轮询失败不中断，继续重试
      continue;
    }

    // 跟踪后端 updated_at 变化，判断任务是否在推进
    const jobUpdatedAt = job.updated_at || 0;
    if (jobUpdatedAt > lastUpdatedAt) {
      lastUpdatedAt = jobUpdatedAt;
      _lastProgressTime = Date.now();  // 后端有推进，刷新本地卡住检测基准
    }

    // 构建 stepsState
    const stepsState = {};
    let runningStep = null;
    if (job.steps && Array.isArray(job.steps)) {
      for (const s of job.steps) {
        stepsState[s.step] = s.status;
        if (s.status === 'running') runningStep = s.step;
      }
    }
    _currentRunningStep = runningStep;

    // ===== 分级超时提醒（不等 2 小时才告知用户）=====
    const elapsedSec = (Date.now() - t0) / 1000;

    // 进入 avatar（Wav2Lip）步骤时立即提示耗时
    if (runningStep === 'avatar' && !_tierAlerts.avatar_enter) {
      _tierAlerts.avatar_enter = true;
      toast('数字人合成（Wav2Lip）已开始，此步骤耗时较长：GPU 约 20-30 分钟，CPU 约 60-120 分钟，请耐心等待', 'info');
    }

    // 卡住检测：后端 updated_at 超过 5 分钟无更新（任务可能卡死）
    if (_lastProgressTime > 0 && (Date.now() - _lastProgressTime > 300000) && !_tierAlerts.stale) {
      _tierAlerts.stale = true;
      toast('⚠ 任务已 5 分钟无进度更新，可能卡住。可点击"重跑此任务"从断点恢复，或等待自动恢复', 'warning');
    }

    // 30 分钟节点：仍在 avatar 步骤时安抚用户
    if (elapsedSec > 1800 && !_tierAlerts.min30) {
      _tierAlerts.min30 = true;
      if (runningStep === 'avatar') {
        toast('数字人合成仍在进行（已 30 分钟）。CPU 模式长文案可能需要 60-120 分钟，属正常范围', 'info');
      } else if (runningStep) {
        toast(`任务已运行 30 分钟，正在执行：${STEP_INFO[runningStep]?.name || runningStep}`, 'info');
      }
    }

    // 60 分钟节点：建议优化方案
    if (elapsedSec > 3600 && !_tierAlerts.min60) {
      _tierAlerts.min60 = true;
      toast('已耗时 60 分钟。如需加速：减少文案长度 / 设置中切换 resize_factor=2 / 使用 GPU 服务器', 'warning');
    }

    // 更新向导页内 pipeline
    if (wizPipeline) {
      wizPipeline.innerHTML = STEP_ORDER.map(step => {
        const info = STEP_INFO[step];
        const status = stepsState[step] || 'pending';
        const icons = { pending: '○', running: '⟳', success: '✓', failed: '✕', skipped: '−' };
        const statusText = { pending: '等待中', running: '执行中...', success: '已完成', failed: '失败', skipped: '已跳过' };
        return `<div class="pipeline-step ${status}"><div class="step-icon">${icons[status] || '○'}</div><div class="step-info"><div class="step-name">${info.icon} ${info.name}</div><div class="step-status">${statusText[status] || status}</div></div></div>`;
      }).join('');
      if (window.lucide) lucide.createIcons();
    }

    // 更新模态框进度
    updateProgressModal(stepsState, job);

    // 检查是否完成
    if (job.status === 'success' || job.status === 'failed') {
      if (_progressTimerId) { clearInterval(_progressTimerId); _progressTimerId = null; }
      const output = job.output || {};
      const result = {
        success: job.status === 'success',
        status: job.status,
        job_id: jobId,
        error: job.error,
        output,
        video_path: output.final_video,
        title: output.title,
        script_text: output.script_text,
        stages: job.steps,
        steps: stepsState,
      };
      if (job.status === 'failed') {
        throw new Error(job.error || '生成失败，请检查配置后重试');
      }
      return result;
    }
  }
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
  // 收集多选发布平台
  const publishPlatforms = Array.from(document.querySelectorAll('#wiz-publish-platforms input[type="checkbox"]:checked'))
    .map(cb => cb.value);
  const platform = publishPlatforms[0] || 'douyin';  // 向后兼容：单个平台字符串
  const autoPublish = document.getElementById('wiz-auto-publish').checked;

  // 自动发布开启但未选平台时提示
  if (autoPublish && publishPlatforms.length === 0) {
    toast('请至少选择一个发布平台，或关闭自动发布', 'error');
    return;
  }

  const btn = document.getElementById('wiz-generate-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 生成中...';

  // 渲染初始进度（向导页内）
  const wizPipeline = document.getElementById('wiz-pipeline');
  if (wizPipeline) wizPipeline.innerHTML = STEP_ORDER.map(step => {
    const info = STEP_INFO[step];
    return `<div class="pipeline-step pending"><div class="step-icon">○</div><div class="step-info"><div class="step-name">${info.icon} ${info.name}</div><div class="step-status">等待中</div></div></div>`;
  }).join('');
  if (window.lucide) lucide.createIcons();

  // 显示进度模态框
  showProgressModal();

  try {
    // 先保存所有配置
    await Promise.all([
      api('/api/settings/scene', { method: 'PUT', body: { section: 'scene', data: collectWizardScene() } }).catch(() => {}),
      api('/api/settings/audio', { method: 'PUT', body: { section: 'audio', data: collectWizardAudioWithBgm() } }).catch(() => {}),
      api('/api/settings/subtitle', { method: 'PUT', body: { section: 'subtitle', data: collectWizardSubtitle() } }).catch(() => {}),
      api('/api/settings/effects', { method: 'PUT', body: { section: 'effects', data: collectWizardEffects() } }).catch(() => {}),
      api('/api/settings/cover', { method: 'PUT', body: { section: 'cover', data: { style_id: _coverSelectedStyle } } }).catch(() => {}),
    ]);

    // 前后联动：文案已在前端处理过（提取/AI润色/AI生成）时，跳过重复的 script_extract 和 script_write
    // script_mode=raw：后端直接使用前端传来的文案，不再调用 LLM 润色
    // reference_video_url=null：已有文案时不再触发后端重复提取（省去 Playwright+ASR 数分钟耗时）
    const scriptMode = wizardState.scriptProcessed ? 'raw' : 'polish';
    const refUrlForGen = (wizardState.scriptProcessed && script) ? null : (refUrl || null);

    const result = await pollGenerateJob({
      script, reference_video_url: refUrlForGen,
      avatar_id: avatar, voice_id: voice,
      script_mode: scriptMode, platform, auto_publish: autoPublish,
      publish_platforms: publishPlatforms.length > 0 ? publishPlatforms : undefined,
      broll_clips: getWizardBrollClips(),
    });

    // 展示结果（向导页内）
    _displayWizardResult(result);

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
    setBtnIcon(btn, 'rocket', '开始生成视频');
  }
}

// ========== 进度模态框 ==========

let _progressStartTime = 0;
let _currentJobId = null;            // 当前轮询的任务 ID，供失败后"重跑此任务"使用
let _currentRunningStep = null;      // 当前正在执行的步骤名，供计时器显示
let _lastProgressTime = 0;           // 后端 updated_at 最后一次推进的本地时间，用于卡住检测
let _tierAlerts = { avatar_enter: false, min30: false, min60: false, stale: false };

// 步骤预估耗时权重（秒，GPU 模式参考值），用于计算预计剩余时间
const STEP_ETA_WEIGHTS = {
  script_extract: 90, script_write: 10, tts: 20, avatar: 1500,
  subtitle: 15, compose: 45, title: 8, cover: 8, publish: 20,
};

function showProgressModal() {
  const modal = document.getElementById('progress-modal');
  if (!modal) return;
  _progressStartTime = Date.now();
  _currentRunningStep = null;
  modal.style.display = 'flex';
  document.getElementById('progress-modal-title').textContent = '正在生成视频...';
  document.getElementById('progress-modal-close').style.display = 'none';
  document.getElementById('progress-modal-result').style.display = 'none';
  document.getElementById('progress-bar-fill').style.width = '0%';
  document.getElementById('progress-percent').textContent = '0%';
  document.getElementById('progress-eta').textContent = '已用时 0分0秒 · 正在执行：初始化';
  const hintEl = document.getElementById('progress-hint');
  if (hintEl) { hintEl.style.display = 'none'; hintEl.textContent = ''; }
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

// 步骤特别提示（进入 running 时显示，帮助用户理解耗时原因）
const STEP_HINTS = {
  avatar: '⏳ 数字人合成（Wav2Lip）耗时较长：GPU 约 15-30 分钟，CPU 约 60-120 分钟。此步骤期间任务无新进度属正常现象，请耐心等待',
  script_extract: '正在提取文案（下载视频 + ASR 转写），约 1-3 分钟',
  tts: '正在合成语音，约 10-30 秒',
  compose: '正在合成最终视频（字幕+BGM+水印），约 30-60 秒',
};

function updateProgressModal(stepsState, result) {
  const stagesEl = document.getElementById('progress-stages');
  if (!stagesEl) return;
  const icons = { pending: '○', running: '⟳', success: '✓', failed: '✕', skipped: '✓' };
  const statusText = { pending: '等待中', running: '执行中', success: '已完成', failed: '失败', skipped: '已完成' };
  let completed = 0;
  let failed = 0;
  let runningStepName = null;
  stagesEl.querySelectorAll('.progress-stage').forEach(stage => {
    const step = stage.dataset.step;
    const status = stepsState[step] || 'pending';
    stage.className = `progress-stage ${status}`;
    stage.querySelector('.progress-stage-icon').textContent = icons[status] || '○';
    stage.querySelector('.progress-stage-status').textContent = statusText[status] || status;
    if (status === 'success' || status === 'skipped') completed++;
    if (status === 'failed') failed++;
    if (status === 'running') runningStepName = step;
  });
  // 进度百分比
  const percent = Math.round((completed / STEP_ORDER.length) * 100);
  document.getElementById('progress-bar-fill').style.width = percent + '%';
  document.getElementById('progress-percent').textContent = percent + '%';

  // 步骤提示 + 加权预估剩余时间（progress-hint 由本函数独占，progress-eta 由计时器独占）
  const hintEl = document.getElementById('progress-hint');
  const elapsed = (Date.now() - _progressStartTime) / 1000;
  if (hintEl) {
    if (completed >= STEP_ORDER.length) {
      hintEl.style.display = 'block';
      hintEl.textContent = `✓ 全部完成 · 用时 ${Math.floor(elapsed / 60)}分${Math.floor(elapsed % 60)}秒`;
    } else if (runningStepName && STEP_HINTS[runningStepName]) {
      hintEl.style.display = 'block';
      hintEl.textContent = STEP_HINTS[runningStepName];
    } else if (runningStepName) {
      hintEl.style.display = 'block';
      hintEl.textContent = `正在执行：${STEP_INFO[runningStepName]?.name || runningStepName}`;
    } else {
      hintEl.style.display = 'none';
    }
  }

  // 完成或失败时显示结果
  const isDone = result && (result.success || result.status === 'success' || result.status === 'failed' || failed > 0 || completed >= STEP_ORDER.length);
  if (isDone) {
    finishProgressModal(result, failed > 0 || result.status === 'failed');
  }
}

function finishProgressModal(result, hasFailed) {
  document.getElementById('progress-modal-title').textContent = hasFailed ? '生成未完全成功' : '视频生成成功！';
  document.getElementById('progress-modal-close').style.display = 'flex';
  const resultEl = document.getElementById('progress-modal-result');
  const output = result.output || {};
  const videoPath = output.final_video;
  const videoAbsPath = output.final_video_absolute || videoPath;
  const title = output.title || '';
  // 重跑按钮（失败或无视频时显示，支持断点续跑）
  const rerunBtn = (_currentJobId && (hasFailed || !videoPath))
    ? `<button class="btn btn-primary" type="button" onclick="rerunCurrentJob()"><i data-lucide="rotate-cw"></i> 重跑此任务（断点续跑）</button>`
    : '';
  if (videoPath) {
    resultEl.innerHTML = `
      <div class="progress-modal-result-title">${escapeHtml(title)}</div>
      <video src="/api/files?path=${encodeURIComponent(videoPath)}" controls autoplay></video>
      <div class="progress-modal-result-actions">
        <div class="video-path-display" style="flex:1;text-align:left;padding:8px 12px;background:var(--bg-elevated);border-radius:8px;font-size:12px;color:var(--text-secondary);font-family:var(--font-mono);word-break:break-all"><i data-lucide="folder" style="width:14px;height:14px;vertical-align:middle;margin-right:4px"></i>${escapeHtml(videoAbsPath)}</div>
        <button class="btn btn-secondary" type="button" onclick="copyToClipboard('${videoAbsPath.replace(/'/g, "\\'")}')"><i data-lucide="copy"></i> 复制路径</button>
        ${_currentJobId ? `<button class="btn btn-secondary" type="button" onclick="openJobFolder('${_currentJobId}')"><i data-lucide="folder-open"></i> 打开目录</button>` : ''}
        ${rerunBtn}
        <button class="btn btn-secondary" type="button" onclick="closeProgressModal()"><i data-lucide="refresh-cw"></i> 再做一个</button>
      </div>
    `;
  } else {
    resultEl.innerHTML = `
      <div class="progress-modal-result-title">视频未生成</div>
      <div class="progress-modal-result-actions">
        ${_currentJobId ? `<button class="btn btn-secondary" type="button" onclick="openJobFolder('${_currentJobId}')"><i data-lucide="folder-open"></i> 打开目录</button>` : ''}
        ${rerunBtn}
        <button class="btn btn-secondary" type="button" onclick="closeProgressModal()"><i data-lucide="refresh-cw"></i> 再做一个</button>
      </div>
    `;
  }
  resultEl.style.display = 'block';
  if (window.lucide) lucide.createIcons();
}

function finishProgressModalError(message) {
  document.getElementById('progress-modal-title').textContent = '生成失败';
  document.getElementById('progress-modal-close').style.display = 'flex';
  const resultEl = document.getElementById('progress-modal-result');
  // 重跑按钮（有 job_id 时显示，支持断点续跑从失败步骤恢复）
  const rerunBtn = _currentJobId
    ? `<button class="btn btn-primary" type="button" onclick="rerunCurrentJob()"><i data-lucide="rotate-cw"></i> 重跑此任务（断点续跑）</button>`
    : '';
  resultEl.innerHTML = `
    <div class="progress-modal-result-title" style="color:var(--color-error)"><i data-lucide="x-circle"></i> ${escapeHtml(message)}</div>
    <div class="progress-modal-result-actions">
      ${rerunBtn}
      ${_currentJobId ? `<button class="btn btn-secondary" type="button" onclick="openJobFolder('${_currentJobId}')"><i data-lucide="folder-open"></i> 打开目录</button>` : ''}
      <button class="btn btn-secondary" type="button" onclick="navigate('jobs')"><i data-lucide="clipboard-list"></i> 查看任务列表</button>
      <button class="btn btn-secondary" type="button" onclick="closeProgressModal()">关闭</button>
    </div>
  `;
  resultEl.style.display = 'block';
  if (window.lucide) lucide.createIcons();
}

function closeProgressModal() {
  const modal = document.getElementById('progress-modal');
  if (modal) modal.style.display = 'none';
}

// ========== 模板中心页面 ==========

async function loadTemplatesCenter() {
  try {
    const grid = document.getElementById('templates-grid');
    if (!grid) return;
    showSkeletonCards(grid, 6);
    const templates = await ensureTemplates();
    grid.innerHTML = Object.entries(templates).map(([key, tpl]) => `
      <div class="template-card" data-key="${key}">
        <div class="template-card-icon"><i data-lucide="${tpl.icon}"></i></div>
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
    if (window.lucide) lucide.createIcons();
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
    const grid = document.getElementById('scene-templates-grid');
    if (!grid) return;
    showSkeletonCards(grid, 6);
    const resp = await fetch('/api/scene/templates');
    const data = await resp.json();
    sceneState.templates = data.templates || {};
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
          <div class="scene-icon">${tpl.icon || '<i data-lucide="clipboard-list"></i>'}</div>
          <div class="scene-label">${tpl.label}</div>
          <div class="scene-category">${tpl.category || '其他'}</div>
          <div class="scene-desc">${tpl.description || ''}</div>
          <div class="scene-style-tags">
            ${styleTags.map(t => `<span class="scene-style-tag">${t}</span>`).join('')}
          </div>
        </div>
      `;
    }).join('');
    if (window.lucide) lucide.createIcons();
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
    document.getElementById('scene-modal-title').innerHTML = `${tpl.icon || '<i data-lucide="clipboard-list"></i>'} ${tpl.label} - 场景创作`;
    // 渲染占位符输入表单
    const body = document.getElementById('scene-modal-body');
    const placeholders = tpl.placeholders || {};
    let html = `
      <div style="margin-bottom:16px;padding:12px;background:rgba(16,185,129,0.08);border-left:3px solid #10b981;border-radius:4px;font-size:12px;color:var(--text-secondary);line-height:1.5">
        <strong><i data-lucide="pen-line"></i> 文案骨架：</strong>填入下方关键词，系统将自动生成完整口播文案。每个字段都有示例提示，照着填即可。
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
    html += `<div id="scene-script-preview" style="display:none"><div style="font-size:12px;font-weight:600;margin-top:12px;margin-bottom:6px;display:flex;align-items:center;gap:4px"><i data-lucide="file-text"></i> 生成文案预览</div><div class="scene-preview-script" id="scene-preview-content"></div></div>`;
    body.innerHTML = html;
    if (window.lucide) lucide.createIcons();
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
    btn.innerHTML = '<span class="spinner"></span> 生成中...';
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
    btn.innerHTML = '<i data-lucide="sparkles"></i> 生成文案';
    if (window.lucide) lucide.createIcons();
  }
}

// 一键应用场景样式（字幕/BGM/滤镜/转场/情感/语速）
async function applySceneStyle() {
  if (!sceneState.currentTemplate) return;
  const tid = sceneState.currentTemplate.id;
  try {
    const btn = document.getElementById('scene-apply-style-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> 应用中...';
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
    btn.innerHTML = '<i data-lucide="wand-2"></i> 一键应用样式';
    if (window.lucide) lucide.createIcons();
  }
}

// 加载预制形象库
async function loadPresetAvatars() {
  try {
    const grid = document.getElementById('preset-avatars-grid');
    if (!grid) return;
    showSkeletonCards(grid, 6);
    const resp = await fetch('/api/presets/avatars');
    const data = await resp.json();
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
          <div class="preset-avatar-icon" style="display:none">${info.icon || '<i data-lucide="user-round"></i>'}</div>
          <div class="preset-avatar-name">${info.label}</div>
          <div class="preset-avatar-desc">${info.description || ''}</div>
          <div class="preset-avatar-scenes">适合: ${scenes}</div>
          <button class="btn btn-sm btn-primary btn-block" onclick="usePresetAvatar('${aid}', '${info.recommended_voice || ''}', '${info.recommended_emotion || ''}')">使用此形象</button>
        </div>
      `;
    }).join('');
    if (window.lucide) lucide.createIcons();
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

    // 2. 设置推荐音色（使用 api helper，正确格式请求体）
    if (voice) {
      const ttsData = await api('/api/settings/tts');
      ttsData.default_voice = voice;
      // edge_tts 音色 ID 以 zh-CN 开头，若选的是 edge 音色则确保 provider 一致
      if (voice.startsWith('zh-CN-') && ttsData.provider !== 'edge_tts') {
        ttsData.provider = 'edge_tts';
      }
      await api('/api/settings/tts', {
        method: 'PUT',
        body: { section: 'tts', data: ttsData },
      });
      // 使向导音色库缓存失效
      window._wizardVoiceList = null;
    }

    // 3. 跳转到创作向导并预选该形象
    wizardState.presetAvatarId = targetAvatarId;
    navigate('wizard');
    // 向导数据加载后刷新形象列表并预选
    setTimeout(async () => {
      try {
        const [avatars, presetAvatars] = await Promise.all([
          api('/api/avatars').catch(() => []),
          api('/api/presets/avatars').catch(() => ({ avatars: {} })),
        ]);
        if (avatars && avatars.length) {
          const gm = {};
          if (presetAvatars && presetAvatars.avatars) {
            Object.entries(presetAvatars.avatars).forEach(([aid, info]) => { gm[aid] = info.gender || ''; });
          }
          renderWizardAvatarGrid(avatars, gm);
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
    const grid = document.getElementById('preset-voices-grid');
    if (!grid) return;
    showSkeletonCards(grid, 6);
    const resp = await fetch('/api/presets/voices');
    const data = await resp.json();
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
    // 读取当前 TTS 配置，仅更新 default_voice，不强制切换 provider
    const ttsData = await api('/api/settings/tts');
    ttsData.default_voice = voiceId;
    // edge_tts 音色 ID 以 zh-CN 开头，若选的是 edge 音色则确保 provider 一致
    if (voiceId.startsWith('zh-CN-') && ttsData.provider !== 'edge_tts') {
      ttsData.provider = 'edge_tts';
    }
    const result = await api('/api/settings/tts', {
      method: 'PUT',
      body: { section: 'tts', data: ttsData },
    });
    if (result.success) {
      toast(`已设置默认音色: ${voiceId}`, 'success');
      // 使向导音色库缓存失效，下次进入向导时刷新
      window._wizardVoiceList = null;
    } else {
      toast(`设置失败: ${result.message || '未知错误'}`, 'error');
    }
  } catch (e) {
    toast(`设置失败: ${e.message}`, 'error');
  }
}

// ========== 一键生成页面 ==========

const STEP_INFO = {
  script_extract: { name: '文案提取', icon: '<i data-lucide="pen-line"></i>' },
  script_write: { name: '文案仿写', icon: '<i data-lucide="pen-line"></i>' },
  tts: { name: '语音合成', icon: '<i data-lucide="mic"></i>' },
  avatar: { name: '数字人生成', icon: '<i data-lucide="user-round"></i>' },
  subtitle: { name: '字幕生成', icon: '<i data-lucide="message-square"></i>' },
  compose: { name: '视频合成', icon: '<i data-lucide="film"></i>' },
  title: { name: '标题生成', icon: '<i data-lucide="pin"></i>' },
  cover: { name: '封面生成', icon: '<i data-lucide="image"></i>' },
  publish: { name: '多平台发布', icon: '<i data-lucide="share-2"></i>' },
};

const STEP_ORDER = ['script_extract', 'script_write', 'tts', 'avatar', 'subtitle', 'compose', 'title', 'cover', 'publish'];

function renderPipeline(stepsState = {}) {
  const container = document.getElementById('pipeline');
  container.innerHTML = STEP_ORDER.map(step => {
    const info = STEP_INFO[step];
    const status = stepsState[step] || 'pending';
    const icons = {
      pending: '○', running: '⟳', success: '✓', failed: '✕', skipped: '✓',
    };
    const statusText = {
      pending: '等待中', running: '执行中...', success: '已完成', failed: '失败', skipped: '已完成',
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
  if (window.lucide) lucide.createIcons();
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

  // 统一进度反馈：显示全局进度模态框（与创作向导一致）
  showProgressModal();
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
    updateProgressModal(stepsState, result);

    // 完成进度模态框（统一成功/失败反馈）
    const hasFailed = !result.success;
    finishProgressModal(result, hasFailed);

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
    finishProgressModalError(e.message);
    toast(`生成失败: ${e.message}`, 'error');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '开始生成视频';
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
    setBtnIcon(btn, 'play', '执行此模块');
  }
}

// ========== 任务管理页面 ==========

async function loadJobs() {
  try {
    const tbody = document.getElementById('jobs-tbody');
    if (tbody) showSkeletonRows(tbody, 5);
    const jobs = await api('/api/jobs?limit=50');
    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:40px;color:var(--text-muted)">暂无任务</td></tr>';
      return;
    }
    tbody.innerHTML = jobs.map(j => {
      const output = j.output || {};
      const videoPath = output.final_video || output.video_path;
      const hasVideo = j.status === 'success' && videoPath;
      return `
      <tr>
        <td style="font-family:var(--font-mono);font-size:12px">${j.job_id}</td>
        <td>${statusBadge(j.status)}</td>
        <td>${formatTime(j.created_at)}</td>
        <td>${formatTime(j.updated_at)}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="showJobDetail('${j.job_id}')">详情</button>
          ${hasVideo ? `<a class="btn btn-sm btn-primary" href="/api/files?path=${encodeURIComponent(videoPath)}" download="${j.job_id}.mp4">下载</a>` : ''}
          <button class="btn btn-sm btn-secondary" onclick="rerunJob('${j.job_id}')">续跑</button>
          <button class="btn btn-sm btn-danger" onclick="deleteJob('${j.job_id}')">删除</button>
        </td>
      </tr>
    `;
    }).join('');
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
    const output = job.output || {};
    const videoPath = output.final_video || output.video_path;
    const videoAbsPath = output.final_video_absolute || output.video_path_absolute || videoPath;
    const hasVideo = job.status === 'success' && videoPath;
    detail.innerHTML = `
      <div style="margin-bottom:16px">
        <strong>任务 ID:</strong> ${job.job_id}<br>
        <strong>状态:</strong> ${statusBadge(job.status)}<br>
        <strong>创建时间:</strong> ${formatTime(job.created_at)}
      </div>
      ${hasVideo ? `
        <div style="margin-bottom:16px">
          <div style="font-weight:600;margin-bottom:8px">生成结果</div>
          <video src="/api/files?path=${encodeURIComponent(videoPath)}" controls style="max-width:100%;border-radius:8px;margin-bottom:8px"></video>
          <div style="display:flex;gap:8px">
            <a class="btn btn-sm btn-primary" href="/api/files?path=${encodeURIComponent(videoPath)}" download="${job.job_id}.mp4">
              <i data-lucide="download"></i> 下载视频
            </a>
            <button class="btn btn-sm btn-secondary" onclick="copyToClipboard('${videoAbsPath.replace(/\\/g, '\\\\')}')">
              <i data-lucide="copy"></i> 复制路径
            </button>
            <button class="btn btn-sm btn-secondary" onclick="openJobFolder('${job.job_id}')">
              <i data-lucide="folder-open"></i> 打开目录
            </button>
          </div>
        </div>
      ` : ''}
      <div class="pipeline">${stepsHtml}</div>
      ${job.error ? `<div style="margin-top:12px;color:var(--color-error)">错误: ${job.error}</div>` : ''}
    `;
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    toast(`加载详情失败: ${e.message}`, 'error');
  }
}

async function rerunJob(jobId) {
  if (!confirm(`确定要续跑任务 ${jobId} 吗？`)) return;
  try {
    toast('已开始续跑任务（断点续跑），可在列表查看状态', 'info');
    // 使用异步端点，避免长任务阻塞 HTTP 请求
    const result = await api(`/api/jobs/${jobId}/rerun/async`, { method: 'POST' });
    if (result.job_id) {
      _currentJobId = jobId;  // 记录当前任务，供向导页"重跑此任务"使用
      loadJobs();
    } else {
      toast('续跑请求失败', 'error');
    }
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
    const grid = document.getElementById('avatars-grid');
    if (grid) showSkeletonCards(grid, 6);
    const avatars = await api('/api/avatars');
    if (!avatars.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="user-round"></i></div><div>暂无已注册形象</div><div style="font-size:12px;color:#999;margin-top:6px">请上传真人照片/视频注册</div></div>';
      if (window.lucide) lucide.createIcons();
      return;
    }
    grid.innerHTML = avatars.map(a => {
      const mode = a.meta?.mode || 'mock';
      const hasLipSync = a.meta?.has_lip_sync || mode === 'wav2lip';
      const refType = a.meta?.reference_type || (a.reference_image ? 'photo' : 'unknown');
      const lipBadge = hasLipSync
        ? '<span style="color:#10b981;font-size:11px;display:inline-flex;align-items:center;gap:2px"><i data-lucide="smile" style="width:12px;height:12px"></i> 唇形同步</span>'
        : '<span style="color:#999;font-size:11px">静态图</span>';
      const modeBadge = `<span style="color:#6b7280;font-size:11px">${mode}</span>`;
      // 参考图预览
      let imgHtml = '<div style="width:100%;height:120px;background:#f5f5f5;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#bbb">无预览</div>';
      if (a.reference_image || hasLipSync || mode !== 'mock') {
        imgHtml = `<img src="/api/avatars/${encodeURIComponent(a.avatar_id)}/preview" style="width:100%;height:120px;object-fit:cover;border-radius:6px" onerror="this.outerHTML='<div style=&quot;width:100%;height:120px;background:#f5f5f5;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#bbb&quot;>无预览</div>'">`;
      }
      const isDefault = a.avatar_id === 'default';
      return `
        <div class="asset-card" style="padding:10px;position:relative">
          ${imgHtml}
          ${isDefault ? '' : `<button onclick="deleteAvatar('${a.avatar_id}')" title="删除" type="button" style="position:absolute;top:8px;right:8px;background:rgba(239,68,68,0.9);color:#fff;border:none;border-radius:6px;padding:5px;cursor:pointer;display:flex;align-items:center"><i data-lucide="trash-2" style="width:14px;height:14px"></i></button>`}
          <div class="asset-id" style="margin-top:8px">${a.avatar_id}</div>
          <div style="display:flex;gap:8px;margin-top:4px">${lipBadge} ${modeBadge}</div>
          ${refType === 'video' ? '<div style="font-size:11px;color:#6b7280;margin-top:2px;display:flex;align-items:center;gap:3px"><i data-lucide="video" style="width:12px;height:12px"></i> 视频参考</div>' : ''}
        </div>
      `;
    }).join('');
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    toast(`加载形象失败: ${e.message}`, 'error');
  }
}

async function handleRegisterAvatar() {
  const avatarIdInput = document.getElementById('avatar-id');
  const avatarId = avatarIdInput.value.trim();
  const fileInput = document.getElementById('avatar-file');
  if (!avatarId) { setFieldError(avatarIdInput, '请输入形象 ID'); toast('请输入形象 ID', 'error'); return; }
  if (!isValidId(avatarId)) { setFieldError(avatarIdInput, 'ID 只能包含英文字母和数字（3-32位）'); toast('形象 ID 格式不正确', 'error'); return; }
  setFieldSuccess(avatarIdInput);
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
      // 联动 P2：广播形象变更事件，通知向导刷新形象列表
      window.dispatchEvent(new CustomEvent('enlyai:avatars-changed'));
    } else {
      toast('注册失败', 'error');
    }
  } catch (e) {
    toast(`注册失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    setBtnIcon(btn, 'download', '注册形象（Wav2Lip 唇形同步）');
  }
}

// ========== 音色管理页面 ==========

async function loadVoices() {
  try {
    const grid = document.getElementById('voices-grid');
    if (grid) showSkeletonCards(grid, 6);
    const voices = await api('/api/voices');
    if (!voices.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="mic"></i></div><div>暂无已注册音色</div></div>';
      if (window.lucide) lucide.createIcons();
      return;
    }
    grid.innerHTML = voices.map(v => {
      const isCustom = v.type === 'custom';
      const providerLabel = v.provider === 'moss_nano' ? 'MOSS' : (v.provider === 'edge_tts' ? 'Edge' : (v.provider || ''));
      const typeLabel = v.type === 'preset' ? '预制' : (v.type === 'provider_default' ? '默认' : '克隆');
      const genderIcon = v.gender === 'female' ? '👩' : (v.gender === 'male' ? '👨' : '🎵');
      const displayName = v.label || v.voice_id;
      const actions = [];
      actions.push(`<button class="voice-preview-btn" data-voice="${v.voice_id}" type="button" title="试听" style="background:#f5f5f5;color:#333;border:none;border-radius:6px;padding:6px;cursor:pointer;display:flex;align-items:center"><i data-lucide="play" style="width:14px;height:14px"></i></button>`);
      if (isCustom) {
        actions.push(`<button onclick="deleteVoice('${v.voice_id}')" title="删除" type="button" style="background:rgba(239,68,68,0.1);color:#ef4444;border:none;border-radius:6px;padding:6px;cursor:pointer;display:flex;align-items:center"><i data-lucide="trash-2" style="width:14px;height:14px"></i></button>`);
      }
      return `
        <div class="asset-card" style="padding:10px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
            <div style="flex:1;min-width:0">
              <div class="asset-id">${genderIcon} ${displayName}</div>
              <div style="font-size:11px;color:#999;margin-top:4px">${typeLabel} · ${providerLabel}</div>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0">${actions.join('')}</div>
          </div>
          ${v.description ? `<div style="font-size:12px;color:#6b7280;margin-top:6px">${v.description}</div>` : ''}
        </div>
      `;
    }).join('');
    // 绑定试听按钮事件
    grid.querySelectorAll('.voice-preview-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        playVoicePreview(btn.dataset.voice, btn);
      });
    });
  } catch (e) {
    toast(`加载音色失败: ${e.message}`, 'error');
  }
}

async function deleteAvatar(avatarId) {
  if (avatarId === 'default') { toast('默认形象不可删除', 'error'); return; }
  if (!confirm(`确定删除形象「${avatarId}」？此操作不可恢复。`)) return;
  try {
    await api(`/api/avatars/${encodeURIComponent(avatarId)}`, { method: 'DELETE' });
    toast('形象已删除', 'success');
    loadAvatars();
    // 联动 P2：广播形象变更事件，通知向导刷新形象列表
    window.dispatchEvent(new CustomEvent('enlyai:avatars-changed'));
  } catch (e) {
    toast(`删除失败: ${e.message}`, 'error');
  }
}

async function deleteVoice(voiceId) {
  if (!confirm(`确定删除音色「${voiceId}」？此操作不可恢复。`)) return;
  try {
    await api(`/api/voices/${encodeURIComponent(voiceId)}`, { method: 'DELETE' });
    toast('音色已删除', 'success');
    loadVoices();
    // 联动 P2：广播音色变更事件，通知向导刷新音色列表
    window.dispatchEvent(new CustomEvent('enlyai:voices-changed'));
  } catch (e) {
    toast(`删除失败: ${e.message}`, 'error');
  }
}

async function handleRegisterVoice() {
  const voiceIdInput = document.getElementById('voice-id');
  const voiceId = voiceIdInput.value.trim();
  const fileInput = document.getElementById('voice-file');
  if (!voiceId) { setFieldError(voiceIdInput, '请输入音色 ID'); toast('请输入音色 ID', 'error'); return; }
  if (!isValidId(voiceId)) { setFieldError(voiceIdInput, 'ID 只能包含英文字母和数字（3-32位）'); toast('音色 ID 格式不正确', 'error'); return; }
  setFieldSuccess(voiceIdInput);
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
      // 联动 P2：广播音色变更事件，通知向导刷新音色列表
      window.dispatchEvent(new CustomEvent('enlyai:voices-changed'));
    }
  } catch (e) {
    toast(`注册失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    setBtnIcon(btn, 'download', '注册音色');
  }
}

// ========== 向导内声音克隆上传（对标必火AI） ==========
async function onWizardVoiceClone(fileInput) {
  const statusEl = document.getElementById('wiz-clone-status');
  const voiceIdInput = document.getElementById('wiz-clone-voice-id');
  const file = fileInput.files[0];
  if (!file) return;

  // 自动生成音色ID（若用户未输入）
  let voiceId = voiceIdInput.value.trim();
  if (!voiceId) {
    voiceId = 'clone_' + Date.now().toString(36);
    voiceIdInput.value = voiceId;
  }
  // 确保ID合法（仅字母数字）
  voiceId = voiceId.replace(/[^a-zA-Z0-9_]/g, '_');

  if (statusEl) statusEl.textContent = '上传中...';
  const formData = new FormData();
  formData.append('voice_id', voiceId);
  formData.append('file', file);

  try {
    const resp = await fetch('/api/voices/register', { method: 'POST', body: formData });
    const result = await resp.json();
    if (result.success) {
      if (statusEl) statusEl.textContent = '✓ 克隆成功！音色已添加到列表';
      toast('声音克隆成功，已添加到音色列表', 'success');
      // 刷新向导音色列表
      const voices = await api('/api/voices').catch(() => []);
      renderWizardVoiceGrid(voices);
      // 自动选中新克隆的音色
      setTimeout(() => {
        const grid = document.getElementById('wiz-voice-grid');
        if (grid) {
          const newCard = grid.querySelector(`[data-id="${voiceId}"]`);
          if (newCard) {
            grid.querySelectorAll('.voice-card').forEach(c => c.classList.remove('selected'));
            newCard.classList.add('selected');
            document.getElementById('wiz-voice').value = voiceId;
          }
        }
      }, 200);
      // 联动 P4：广播音色变更事件，通知资源中心音色管理页同步刷新
      window.dispatchEvent(new CustomEvent('enlyai:voices-changed'));
    } else {
      if (statusEl) statusEl.textContent = '✗ 克隆失败：' + (result.error || '未知错误');
      toast('声音克隆失败', 'error');
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = '✗ 上传失败：' + e.message;
    toast('上传失败: ' + e.message, 'error');
  } finally {
    fileInput.value = '';
  }
}

// ========== BGM 试听 ==========
let _bgmPreviewAudio = null;
async function previewBgm() {
  const trackSel = document.getElementById('wiz-bgm-track');
  const btn = document.getElementById('wiz-bgm-preview-btn');
  if (!trackSel || !trackSel.value) { toast('请先选择BGM曲目', 'error'); return; }

  // 如果正在播放，停止
  if (_bgmPreviewAudio && !_bgmPreviewAudio.paused) {
    _bgmPreviewAudio.pause();
    if (btn) setBtnIcon(btn, 'play', '');
    return;
  }

  // 加载期间显示 loading（避免点击后无反馈）
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> 加载中...';
    if (window.lucide) lucide.createIcons();
  }

  try {
    const url = `/api/bgm/preview/${trackSel.value}`;
    _bgmPreviewAudio = new Audio(url);
    _bgmPreviewAudio.volume = 0.5;
    // 音频加载完成后才切到停止图标
    _bgmPreviewAudio.addEventListener('canplay', () => {
      if (btn) setBtnIcon(btn, 'square', '');
      toast('BGM 试听播放中', 'info');
    });
    _bgmPreviewAudio.play();
    _bgmPreviewAudio.onended = () => { if (btn) setBtnIcon(btn, 'play', ''); };
    _bgmPreviewAudio.onerror = () => {
      toast('BGM 试听失败', 'error');
      if (btn) setBtnIcon(btn, 'play', '');
    };
  } catch (e) {
    toast('BGM 试听失败: ' + e.message, 'error');
    if (btn) setBtnIcon(btn, 'play', '');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ========== 系统状态页面 ==========

async function loadHealth() {
  try {
    const health = await api('/api/health');
    const container = document.getElementById('health-content');
    const items = [
      { key: 'ffmpeg', label: 'FFmpeg 视频处理', icon: '<i data-lucide="film"></i>' },
      { key: 'gpu_tts', label: '云端 TTS 服务', icon: '<i data-lucide="mic"></i>' },
      { key: 'gpu_avatar', label: '云端数字人服务', icon: '<i data-lucide="user-round"></i>' },
      { key: 'llm_mock', label: 'LLM 模式', icon: '<i data-lucide="brain"></i>' },
      { key: 'avatars_count', label: '已注册形象', icon: '<i data-lucide="users"></i>' },
      { key: 'voices_count', label: '已注册音色', icon: '<i data-lucide="music"></i>' },
      { key: 'gpu.cuda_available', label: 'GPU CUDA 加速', icon: '<i data-lucide="cpu"></i>' },
      { key: 'gpu.nvenc_available', label: 'NVENC 硬件编码', icon: '<i data-lucide="video"></i>' },
    ];
    container.innerHTML = items.map(item => {
      const val = item.key.includes('.') ? item.key.split('.').reduce((obj, k) => (obj == null ? undefined : obj[k]), health) : health[item.key];
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
            <span style="display:inline-flex;width:24px;height:24px;color:var(--color-primary)">${item.icon}</span>
            <span style="font-weight:600">${item.label}</span>
          </div>
          ${display}
        </div>
      `;
    }).join('');
    if (window.lucide) lucide.createIcons();

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

// ========== 语音博客向导 ==========

// 播客向导状态
let podcastState = {
  currentStep: 1,
  maxVisitedStep: 1,
  source: 'manual',         // manual | url | file | topic
  content: '',               // 提取/输入的原始内容
  script: '',                // 改写后的剧本
  voiceMap: {},              // {角色名: 音色ID}
  voiceList: [],             // 可用音色列表
  jobId: null,               // 当前生成任务 ID
  result: null,              // 生成结果
  pollTimer: null,           // 轮询定时器
  initialized: false,
  // BGM 背景音乐
  bgmList: [],               // BGM 库列表 [{id, label, mood, duration}]
  bgmEnabled: false,         // 是否启用 BGM
  bgmTrack: '',              // 当前选中的 BGM 曲目 ID
  bgmVolume: 0.15,           // BGM 音量（0-1）
  bgmPreviewing: false,      // BGM 试听状态
};

// 初始化播客向导
function initPodcast() {
  if (!podcastState.initialized) {
    podcastState.initialized = true;
    bindPodcastEvents();
    // 异步加载音色列表（不阻塞 UI）
    loadPodcastVoices();
    // 异步加载 BGM 库
    loadPodcastBgmLibrary();
  }
  renderPodcastStepper();
}

// 加载可用音色列表
async function loadPodcastVoices() {
  try {
    const data = await api('/api/podcast/voices');
    podcastState.voiceList = data.voices || [];
  } catch (e) {
    console.warn('加载播客音色列表失败:', e.message);
    podcastState.voiceList = [];
  }
}

// 加载 BGM 素材库（复用 /api/bgm/library）
async function loadPodcastBgmLibrary() {
  try {
    const data = await api('/api/bgm/library');
    // data 是 {track_id: {label, mood, duration}} 字典
    const list = Object.entries(data).map(([id, info]) => ({
      id,
      label: info.label || id,
      mood: info.mood || '',
      duration: info.duration || 0,
    }));
    // 按 mood 分组排序，提升选择体验
    list.sort((a, b) => a.label.localeCompare(b.label, 'zh'));
    podcastState.bgmList = list;

    // 填充下拉框
    const select = document.getElementById('pod-bgm-track');
    if (select) {
      select.innerHTML = list.map(t =>
        `<option value="${t.id}">${t.label}（${t.mood}）</option>`
      ).join('');
      if (list.length > 0) {
        podcastState.bgmTrack = list[0].id;
        select.value = list[0].id;
      }
    }
  } catch (e) {
    console.warn('加载 BGM 库失败:', e.message);
    podcastState.bgmList = [];
    const select = document.getElementById('pod-bgm-track');
    if (select) select.innerHTML = '<option value="">BGM 库加载失败</option>';
  }
}

// 绑定播客向导所有事件
function bindPodcastEvents() {
  // 内容来源 tab 切换
  document.querySelectorAll('[data-pod-source]').forEach(tab => {
    tab.addEventListener('click', () => {
      podcastState.source = tab.dataset.podSource;
      document.querySelectorAll('[data-pod-source]').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.sub-page').forEach(p => {
        if (p.id && p.id.startsWith('pod-source-')) p.classList.remove('active');
      });
      const target = document.getElementById(`pod-source-${tab.dataset.podSource}`);
      if (target) target.classList.add('active');
    });
  });

  // 文章输入字数统计
  const manualText = document.getElementById('pod-manual-text');
  if (manualText) {
    manualText.addEventListener('input', () => {
      document.getElementById('pod-manual-count').textContent = manualText.value.length;
    });
  }

  // URL 提取
  document.getElementById('pod-extract-btn')?.addEventListener('click', podExtractContent);

  // 文件上传
  const fileUpload = document.getElementById('pod-file-upload');
  const fileInput = document.getElementById('pod-file-input');
  if (fileUpload && fileInput) {
    fileUpload.addEventListener('click', () => fileInput.click());
    fileUpload.addEventListener('dragover', (e) => { e.preventDefault(); fileUpload.classList.add('drag-over'); });
    fileUpload.addEventListener('dragleave', () => fileUpload.classList.remove('drag-over'));
    fileUpload.addEventListener('drop', (e) => {
      e.preventDefault();
      fileUpload.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) handlePodcastFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) handlePodcastFile(fileInput.files[0]);
    });
  }

  // AI 改写剧本
  document.getElementById('pod-rewrite-btn')?.addEventListener('click', podRewriteScript);

  // 剧本编辑器字数/角色统计
  const scriptEditor = document.getElementById('pod-script-editor');
  if (scriptEditor) {
    scriptEditor.addEventListener('input', () => updatePodcastScriptStats());
  }

  // 自动匹配音色
  document.getElementById('pod-auto-voice-btn')?.addEventListener('click', podSuggestVoices);
  document.getElementById('pod-clone-voice-btn')?.addEventListener('click', podCloneVoice);

  // 生成设置滑块实时显示
  const sliders = [
    ['pod-switch-pause', 'pod-switch-pause-val', 's'],
    ['pod-same-pause', 'pod-same-pause-val', 's'],
    ['pod-speed', 'pod-speed-val', 'x'],
  ];
  sliders.forEach(([id, valId, suffix]) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', () => {
        document.getElementById(valId).textContent = parseFloat(el.value).toFixed(2) + suffix;
      });
    }
  });

  // BGM 启用开关
  const bgmEnabled = document.getElementById('pod-bgm-enabled');
  const bgmSettings = document.getElementById('pod-bgm-settings');
  if (bgmEnabled && bgmSettings) {
    bgmEnabled.addEventListener('change', () => {
      podcastState.bgmEnabled = bgmEnabled.checked;
      bgmSettings.style.display = bgmEnabled.checked ? 'block' : 'none';
      // 关闭 BGM 时停止试听
      if (!bgmEnabled.checked) stopPodcastBgmPreview();
    });
  }

  // BGM 曲目选择
  const bgmTrack = document.getElementById('pod-bgm-track');
  if (bgmTrack) {
    bgmTrack.addEventListener('change', () => {
      podcastState.bgmTrack = bgmTrack.value;
      // 切换曲目时停止当前试听
      stopPodcastBgmPreview();
    });
  }

  // BGM 音量滑块
  const bgmVolume = document.getElementById('pod-bgm-volume');
  const bgmVolumeVal = document.getElementById('pod-bgm-volume-val');
  if (bgmVolume && bgmVolumeVal) {
    bgmVolume.addEventListener('input', () => {
      const vol = parseFloat(bgmVolume.value);
      podcastState.bgmVolume = vol;
      bgmVolumeVal.textContent = Math.round(vol * 100) + '%';
      // 实时调整试听音量
      const audio = document.getElementById('pod-bgm-audio');
      if (audio) audio.volume = vol;
    });
  }

  // BGM 试听按钮
  document.getElementById('pod-bgm-preview-btn')?.addEventListener('click', togglePodcastBgmPreview);

  // 生成播客
  document.getElementById('pod-generate-btn')?.addEventListener('click', podGenerate);

  // 取消播客任务
  document.getElementById('pod-cancel-btn')?.addEventListener('click', cancelPodcastJob);

  // 重新生成
  document.getElementById('pod-regenerate')?.addEventListener('click', () => {
    document.getElementById('pod-result-section').style.display = 'none';
    document.getElementById('pod-generate-section').style.display = 'block';
    podcastState.result = null;
  });

  // 下载剧本
  document.getElementById('pod-download-script')?.addEventListener('click', () => {
    if (!podcastState.result) return;
    downloadPodcastFile(podcastState.result.script_path, 'podcast_script.txt');
  });

  // 下载字幕
  document.getElementById('pod-download-srt')?.addEventListener('click', () => {
    if (!podcastState.result) return;
    downloadPodcastFile(podcastState.result.srt_path, 'podcast_subtitle.srt');
  });

  // 打开目录
  document.getElementById('pod-open-folder')?.addEventListener('click', () => {
    if (!podcastState.jobId) return;
    api(`/api/podcast/jobs/${podcastState.jobId}/open-folder`, { method: 'POST' })
      .then(() => toast('已打开输出目录', 'success'))
      .catch(e => toast(`打开目录失败: ${e.message}`, 'error'));
  });

  // 步骤导航
  document.getElementById('pod-prev-btn')?.addEventListener('click', () => podcastGoToStep(podcastState.currentStep - 1));
  document.getElementById('pod-next-btn')?.addEventListener('click', podcastNext);
}

// 渲染步骤指示器
function renderPodcastStepper() {
  const steps = document.querySelectorAll('#podcast-stepper .wizard-step');
  const lines = document.querySelectorAll('#podcast-stepper .wizard-step-line');
  steps.forEach(step => {
    const stepNum = parseInt(step.dataset.step);
    step.classList.remove('active', 'completed');
    if (stepNum < podcastState.currentStep) {
      step.classList.add('completed');
    } else if (stepNum === podcastState.currentStep) {
      step.classList.add('active');
    }
  });
  lines.forEach((line, idx) => {
    line.classList.toggle('completed', idx + 1 < podcastState.currentStep);
  });
  // 显示当前面板
  document.querySelectorAll('[id^="podcast-panel-"]').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById(`podcast-panel-${podcastState.currentStep}`);
  if (panel) panel.classList.add('active');
  // 更新导航
  document.getElementById('pod-progress-text-nav').textContent = `第 ${podcastState.currentStep} / 5 步`;
  document.getElementById('pod-prev-btn').disabled = podcastState.currentStep === 1;
  const nextBtn = document.getElementById('pod-next-btn');
  if (podcastState.currentStep === 5) {
    nextBtn.innerHTML = '<i data-lucide="rotate-ccw"></i> 重新开始';
  } else {
    nextBtn.innerHTML = '下一步 <i data-lucide="arrow-right"></i>';
  }
  if (window.lucide) lucide.createIcons();
}

// 步骤跳转
function podcastGoToStep(step) {
  if (step < 1 || step > 5) return;
  podcastState.currentStep = step;
  renderPodcastStepper();
}

// 下一步（含校验）
function podcastNext() {
  if (podcastState.currentStep >= 5) {
    // 重新开始：重置状态
    podcastState.currentStep = 1;
    podcastState.maxVisitedStep = 1;
    podcastState.content = '';
    podcastState.script = '';
    podcastState.voiceMap = {};
    podcastState.result = null;
    podcastState.jobId = null;
    // 清空表单
    document.getElementById('pod-manual-text').value = '';
    document.getElementById('pod-manual-count').textContent = '0';
    document.getElementById('pod-url-input').value = '';
    document.getElementById('pod-extract-preview').innerHTML = '';
    document.getElementById('pod-file-preview').innerHTML = '';
    document.getElementById('pod-topic-input').value = '';
    document.getElementById('pod-script-editor').value = '';
    updatePodcastScriptStats();
    document.getElementById('pod-voice-list').innerHTML = '';
    document.getElementById('pod-result-section').style.display = 'none';
    document.getElementById('pod-progress-section').style.display = 'none';
    document.getElementById('pod-generate-section').style.display = 'block';
    renderPodcastStepper();
    return;
  }

  // 步骤 1 校验：必须有内容
  if (podcastState.currentStep === 1) {
    const content = collectPodcastContent();
    if (!content) {
      toast('请输入或提取内容后再继续', 'error');
      return;
    }
    podcastState.content = content;
  }

  // 步骤 2 校验：必须有剧本
  if (podcastState.currentStep === 2) {
    const script = (document.getElementById('pod-script-editor')?.value || '').trim();
    if (!script) {
      toast('请先生成或粘贴剧本后再继续', 'error');
      return;
    }
    podcastState.script = script;
    // 进入步骤 3 时自动渲染音色列表
    setTimeout(() => renderPodcastVoiceList(), 100);
  }

  // 步骤 3 校验：每个角色必须有音色
  if (podcastState.currentStep === 3) {
    const roles = parsePodcastRoles(podcastState.script);
    const missing = roles.filter(r => !podcastState.voiceMap[r]);
    if (missing.length > 0) {
      toast(`以下角色未分配音色：${missing.join('、')}`, 'error');
      return;
    }
  }

  podcastState.currentStep++;
  podcastState.maxVisitedStep = Math.max(podcastState.maxVisitedStep, podcastState.currentStep);
  renderPodcastStepper();
}

// 收集步骤 1 的内容
function collectPodcastContent() {
  switch (podcastState.source) {
    case 'manual':
      return (document.getElementById('pod-manual-text')?.value || '').trim();
    case 'url':
      return podcastState.content; // 已在提取时保存
    case 'file':
      return podcastState.content; // 已在文件读取时保存
    case 'topic':
      return (document.getElementById('pod-topic-input')?.value || '').trim();
    default:
      return '';
  }
}

// 从网络链接提取内容
async function podExtractContent() {
  const url = (document.getElementById('pod-url-input')?.value || '').trim();
  if (!url) {
    toast('请输入链接', 'error');
    return;
  }
  const btn = document.getElementById('pod-extract-btn');
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> 提取中...';
  if (window.lucide) lucide.createIcons();
  const preview = document.getElementById('pod-extract-preview');
  preview.innerHTML = '<div class="hint" style="text-align:center;padding:16px"><i data-lucide="loader-2" class="spin"></i> 正在提取内容，视频链接可能需要 1-3 分钟...</div>';
  if (window.lucide) lucide.createIcons();
  try {
    const data = await api('/api/podcast/extract', { method: 'POST', body: { url } });
    podcastState.content = data.text;
    preview.innerHTML = `
      <div class="card" style="background:var(--bg-secondary);padding:12px">
        <div class="hint" style="margin-bottom:8px">提取成功 · ${data.char_count} 字</div>
        <div style="max-height:200px;overflow-y:auto;font-size:13px;line-height:1.6;white-space:pre-wrap">${escapeHtml(data.text.substring(0, 2000))}${data.text.length > 2000 ? '\n...(已截断预览)' : ''}</div>
      </div>`;
    if (window.lucide) lucide.createIcons();
    toast(`提取成功，共 ${data.char_count} 字`, 'success');
  } catch (e) {
    preview.innerHTML = `<div class="hint" style="color:var(--color-error)">提取失败：${escapeHtml(e.message)}</div>`;
    toast(`提取失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
    if (window.lucide) lucide.createIcons();
  }
}

// 处理文件上传
function handlePodcastFile(file) {
  if (!file) return;
  if (!/\.(txt|md)$/i.test(file.name)) {
    toast('仅支持 .txt / .md 格式', 'error');
    return;
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    const text = e.target.result;
    podcastState.content = text;
    const preview = document.getElementById('pod-file-preview');
    preview.innerHTML = `
      <div class="card" style="background:var(--bg-secondary);padding:12px">
        <div class="hint" style="margin-bottom:4px"><i data-lucide="file-text"></i> ${escapeHtml(file.name)} · ${text.length} 字</div>
        <div style="max-height:150px;overflow-y:auto;font-size:13px;line-height:1.6;white-space:pre-wrap">${escapeHtml(text.substring(0, 1000))}${text.length > 1000 ? '\n...' : ''}</div>
      </div>`;
    if (window.lucide) lucide.createIcons();
    toast(`文件已加载，共 ${text.length} 字`, 'success');
  };
  reader.onerror = () => toast('文件读取失败', 'error');
  reader.readAsText(file, 'utf-8');
}

// AI 改写剧本
async function podRewriteScript() {
  // 获取内容（如果步骤1未提取，尝试实时收集）
  let content = podcastState.content;
  if (!content) {
    content = collectPodcastContent();
    if (!content) {
      toast('请先在步骤 1 输入或提取内容', 'error');
      return;
    }
    podcastState.content = content;
  }

  const roleCount = parseInt(document.getElementById('pod-role-count').value);
  const duration = parseInt(document.getElementById('pod-duration').value);
  const style = document.getElementById('pod-rewrite-style').value;
  const roleDesc = (document.getElementById('pod-role-desc')?.value || '').trim();
  // 判断模式：topic 为 AI 生成，其他为改写
  const mode = podcastState.source === 'topic' ? 'generate' : 'rewrite';

  const btn = document.getElementById('pod-rewrite-btn');
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> AI 改写中...';
  if (window.lucide) lucide.createIcons();
  try {
    const data = await api('/api/podcast/rewrite', {
      method: 'POST',
      body: { content, mode, role_count: roleCount, style, duration_minutes: duration, role_desc: roleDesc },
    });
    document.getElementById('pod-script-editor').value = data.script;
    podcastState.script = data.script;
    updatePodcastScriptStats();
    toast(`剧本生成成功，共 ${data.char_count} 字`, 'success');
  } catch (e) {
    toast(`改写失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
    if (window.lucide) lucide.createIcons();
  }
}

// 更新剧本统计
function updatePodcastScriptStats() {
  const script = document.getElementById('pod-script-editor')?.value || '';
  document.getElementById('pod-script-count').textContent = script.length;
  const roles = parsePodcastRoles(script);
  document.getElementById('pod-role-count-display').textContent = roles.length;
}

// 解析剧本中的角色列表（按首次出现顺序）
function parsePodcastRoles(script) {
  if (!script) return [];
  const roles = [];
  const seen = new Set();
  const lines = script.split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || trimmed.startsWith('//')) continue;
    const match = trimmed.match(/^([^:：]+)[:：]/);
    if (match) {
      const role = match[1].trim();
      if (role && !seen.has(role)) {
        roles.push(role);
        seen.add(role);
      }
    }
  }
  return roles;
}

// 渲染音色分配列表
function renderPodcastVoiceList() {
  const roles = parsePodcastRoles(podcastState.script || document.getElementById('pod-script-editor')?.value || '');
  const container = document.getElementById('pod-voice-list');
  if (!container) return;
  if (roles.length === 0) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="users"></i></div><div>请先生成剧本</div></div>';
    if (window.lucide) lucide.createIcons();
    return;
  }
  // 如果音色列表为空，尝试加载
  if (podcastState.voiceList.length === 0) {
    container.innerHTML = '<div class="hint" style="text-align:center;padding:16px"><i data-lucide="loader-2" class="spin"></i> 正在加载音色列表...</div>';
    if (window.lucide) lucide.createIcons();
    loadPodcastVoices().then(() => renderPodcastVoiceList());
    return;
  }
  container.innerHTML = roles.map((role, idx) => {
    const currentVoice = podcastState.voiceMap[role] || '';
    const options = podcastState.voiceList.map(v => {
      const voiceId = v.id || v.voice_id || v.name;
      const label = v.label || v.name || voiceId;
      const gender = v.gender ? `（${v.gender}）` : '';
      return `<option value="${escapeHtml(voiceId)}" ${currentVoice === voiceId ? 'selected' : ''}>${escapeHtml(label)}${gender}</option>`;
    }).join('');
    return `
      <div class="voice-assign-row" style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--border-light)">
        <div style="width:40px;height:40px;border-radius:50%;background:var(--bg-secondary);display:flex;align-items:center;justify-content:center;font-weight:600;color:var(--primary)">
          ${escapeHtml(role.substring(0, 2))}
        </div>
        <div style="flex:1">
          <div style="font-weight:600">${escapeHtml(role)}</div>
          <div class="hint">角色 ${idx + 1}</div>
        </div>
        <select class="form-input pod-voice-select" data-role="${escapeHtml(role)}" style="width:200px">
          <option value="">请选择音色</option>
          ${options}
        </select>
        <button class="btn btn-secondary btn-sm pod-voice-preview-btn" data-role="${escapeHtml(role)}" type="button" style="white-space:nowrap" title="试听当前音色">
          <i data-lucide="volume-2"></i>
        </button>
      </div>`;
  }).join('');
  // 绑定音色选择
  container.querySelectorAll('.pod-voice-select').forEach(sel => {
    sel.addEventListener('change', () => {
      const role = sel.dataset.role;
      if (sel.value) {
        podcastState.voiceMap[role] = sel.value;
      } else {
        delete podcastState.voiceMap[role];
      }
    });
  });
  // 绑定试听按钮
  container.querySelectorAll('.pod-voice-preview-btn').forEach(btn => {
    btn.addEventListener('click', () => previewPodcastVoice(btn.dataset.role));
  });
  if (window.lucide) lucide.createIcons();
}

// 音色试听（复用 /api/voice/preview/{voice_id}）
let _podcastVoiceAudio = null;
let _podcastVoicePreviewRole = null;
function previewPodcastVoice(role) {
  // 获取当前角色选中的音色
  const sel = document.querySelector(`.pod-voice-select[data-role="${role}"]`);
  const voiceId = sel?.value || podcastState.voiceMap[role];
  if (!voiceId) {
    toast('请先为该角色选择音色', 'error');
    return;
  }

  // 如果正在试听同一角色，停止播放
  if (_podcastVoicePreviewRole === role && _podcastVoiceAudio && !_podcastVoiceAudio.paused) {
    _podcastVoiceAudio.pause();
    _podcastVoiceAudio.currentTime = 0;
    _resetVoicePreviewBtn(role);
    return;
  }

  // 停止上一个试听
  if (_podcastVoiceAudio) {
    _podcastVoiceAudio.pause();
    if (_podcastVoicePreviewRole) _resetVoicePreviewBtn(_podcastVoicePreviewRole);
  }

  // 开始试听
  const btn = document.querySelector(`.pod-voice-preview-btn[data-role="${role}"]`);
  if (btn) {
    btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i>';
    if (window.lucide) lucide.createIcons();
  }

  if (!_podcastVoiceAudio) {
    _podcastVoiceAudio = new Audio();
  }
  _podcastVoiceAudio.src = `/api/voice/preview/${encodeURIComponent(voiceId)}`;
  _podcastVoicePreviewRole = role;

  _podcastVoiceAudio.play().then(() => {
    if (btn) {
      btn.innerHTML = '<i data-lucide="square"></i>';
      if (window.lucide) lucide.createIcons();
    }
  }).catch(e => {
    toast(`试听失败: ${e.message}`, 'error');
    _resetVoicePreviewBtn(role);
  });

  _podcastVoiceAudio.onended = () => _resetVoicePreviewBtn(role);
  _podcastVoiceAudio.onerror = () => {
    _resetVoicePreviewBtn(role);
    toast('音色试听加载失败', 'error');
  };
}

function _resetVoicePreviewBtn(role) {
  const btn = document.querySelector(`.pod-voice-preview-btn[data-role="${role}"]`);
  if (btn) {
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    if (window.lucide) lucide.createIcons();
  }
  if (_podcastVoicePreviewRole === role) {
    _podcastVoicePreviewRole = null;
  }
}

// 克隆新音色（弹窗上传）
async function podCloneVoice() {
  // 创建弹窗
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center';
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:18px;padding:28px;width:420px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
      <h3 style="font-size:18px;font-weight:600;margin-bottom:16px">克隆新音色</h3>
      <div style="margin-bottom:14px">
        <label style="font-size:13px;color:#6e6e73;display:block;margin-bottom:6px">音色名称（可选，留空自动生成）</label>
        <input type="text" id="pod-clone-id-input" placeholder="如 my_voice" style="width:100%;padding:8px 12px;border:1px solid rgba(0,0,0,0.1);border-radius:10px;font-size:14px">
      </div>
      <div style="margin-bottom:14px">
        <label style="font-size:13px;color:#6e6e73;display:block;margin-bottom:6px">上传参考音频（wav/mp3，5-30秒）</label>
        <div id="pod-clone-upload-area" style="border:2px dashed rgba(0,0,0,0.15);border-radius:14px;padding:24px;text-align:center;cursor:pointer;transition:all 0.2s">
          <div id="pod-clone-file-info" style="color:#6e6e73;font-size:13px">点击选择或拖拽音频文件</div>
        </div>
        <input type="file" id="pod-clone-file-input" accept=".wav,.mp3,.m4a,.flac" style="display:none">
      </div>
      <div id="pod-clone-status" style="font-size:13px;margin-bottom:14px;min-height:18px"></div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-secondary" id="pod-clone-cancel" style="padding:8px 16px;border-radius:10px;border:1px solid rgba(0,0,0,0.1);background:transparent;cursor:pointer;font-size:14px">取消</button>
        <button class="btn btn-primary" id="pod-clone-confirm" style="padding:8px 16px;border-radius:10px;background:#0071e3;color:#fff;border:none;cursor:pointer;font-size:14px" disabled>开始克隆</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const fileInput = overlay.querySelector('#pod-clone-file-input');
  const uploadArea = overlay.querySelector('#pod-clone-upload-area');
  const fileInfo = overlay.querySelector('#pod-clone-file-info');
  const confirmBtn = overlay.querySelector('#pod-clone-confirm');
  const cancelBtn = overlay.querySelector('#pod-clone-cancel');
  const statusEl = overlay.querySelector('#pod-clone-status');
  const idInput = overlay.querySelector('#pod-clone-id-input');
  let selectedFile = null;

  // 点击上传区域
  uploadArea.addEventListener('click', () => fileInput.click());
  // 拖拽
  uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.style.borderColor = '#0071e3'; });
  uploadArea.addEventListener('dragleave', () => { uploadArea.style.borderColor = 'rgba(0,0,0,0.15)'; });
  uploadArea.addEventListener('drop', e => {
    e.preventDefault();
    uploadArea.style.borderColor = 'rgba(0,0,0,0.15)';
    if (e.dataTransfer.files[0]) {
      selectedFile = e.dataTransfer.files[0];
      fileInfo.textContent = selectedFile.name + ' (' + (selectedFile.size / 1024).toFixed(0) + ' KB)';
      confirmBtn.disabled = false;
    }
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) {
      selectedFile = fileInput.files[0];
      fileInfo.textContent = selectedFile.name + ' (' + (selectedFile.size / 1024).toFixed(0) + ' KB)';
      confirmBtn.disabled = false;
    }
  });

  // 取消
  cancelBtn.addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

  // 确认克隆
  confirmBtn.addEventListener('click', async () => {
    if (!selectedFile) return;
    let voiceId = idInput.value.trim();
    if (!voiceId) {
      voiceId = 'clone_' + Date.now().toString(36);
    }
    voiceId = voiceId.replace(/[^a-zA-Z0-9_]/g, '_');

    confirmBtn.disabled = true;
    confirmBtn.textContent = '克隆中...';
    statusEl.style.color = '#6e6e73';
    statusEl.textContent = '正在上传和克隆，请稍候...';

    const formData = new FormData();
    formData.append('voice_id', voiceId);
    formData.append('file', selectedFile);

    try {
      const resp = await fetch('/api/voices/register', { method: 'POST', body: formData });
      const result = await resp.json();
      if (result.success) {
        statusEl.style.color = '#30d158';
        statusEl.textContent = '✓ 克隆成功！正在刷新音色列表...';
        toast('声音克隆成功', 'success');
        // 刷新播客音色列表
        await loadPodcastVoices();
        renderPodcastVoiceList();
        // 广播音色变更
        window.dispatchEvent(new CustomEvent('enlyai:voices-changed'));
        setTimeout(() => overlay.remove(), 1200);
      } else {
        statusEl.style.color = '#ff453a';
        statusEl.textContent = '✗ 克隆失败：' + (result.error || '未知错误');
        confirmBtn.disabled = false;
        confirmBtn.textContent = '开始克隆';
      }
    } catch (e) {
      statusEl.style.color = '#ff453a';
      statusEl.textContent = '✗ 上传失败：' + e.message;
      confirmBtn.disabled = false;
      confirmBtn.textContent = '开始克隆';
    }
  });
}

// 自动匹配音色
async function podSuggestVoices() {
  const script = document.getElementById('pod-script-editor')?.value || podcastState.script || '';
  if (!script.trim()) {
    toast('请先生成剧本', 'error');
    return;
  }
  const btn = document.getElementById('pod-auto-voice-btn');
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> 匹配中...';
  if (window.lucide) lucide.createIcons();
  try {
    const data = await api('/api/podcast/suggest-voices', { method: 'POST', body: { script } });
    // data.voice_map: {role: {voice_id, gender, label}}
    const voiceMap = data.voice_map || {};
    podcastState.voiceMap = {};
    Object.entries(voiceMap).forEach(([role, info]) => {
      podcastState.voiceMap[role] = info.voice_id;
    });
    // 重新渲染列表
    renderPodcastVoiceList();
    // 重新设置选中值
    setTimeout(() => {
      document.querySelectorAll('.pod-voice-select').forEach(sel => {
        const role = sel.dataset.role;
        if (podcastState.voiceMap[role]) {
          sel.value = podcastState.voiceMap[role];
        }
      });
    }, 50);
    toast('音色已自动匹配', 'success');
  } catch (e) {
    toast(`匹配失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
    if (window.lucide) lucide.createIcons();
  }
}

// BGM 试听切换（播放/停止）
function togglePodcastBgmPreview() {
  const audio = document.getElementById('pod-bgm-audio');
  const btn = document.getElementById('pod-bgm-preview-btn');
  if (!audio || !btn) return;

  const track = podcastState.bgmTrack || document.getElementById('pod-bgm-track')?.value;
  if (!track) {
    toast('请先选择 BGM 曲目', 'error');
    return;
  }

  if (podcastState.bgmPreviewing) {
    // 停止试听
    stopPodcastBgmPreview();
    return;
  }

  // 开始试听（复用 /api/bgm/preview/{track}）
  audio.src = `/api/bgm/preview/${encodeURIComponent(track)}`;
  audio.volume = podcastState.bgmVolume;
  audio.play().then(() => {
    podcastState.bgmPreviewing = true;
    btn.innerHTML = '<i data-lucide="square"></i> 停止';
    if (window.lucide) lucide.createIcons();
  }).catch(e => {
    console.warn('BGM 试听失败:', e.message);
    toast(`试听失败: ${e.message}`, 'error');
  });

  // 播放结束自动恢复
  audio.onended = () => {
    stopPodcastBgmPreview();
  };
  audio.onerror = () => {
    stopPodcastBgmPreview();
    toast('BGM 试听加载失败', 'error');
  };
}

// 停止 BGM 试听
function stopPodcastBgmPreview() {
  const audio = document.getElementById('pod-bgm-audio');
  const btn = document.getElementById('pod-bgm-preview-btn');
  if (audio) {
    audio.pause();
    audio.currentTime = 0;
  }
  if (btn && podcastState.bgmPreviewing) {
    btn.innerHTML = '<i data-lucide="play"></i> 试听';
    if (window.lucide) lucide.createIcons();
  }
  podcastState.bgmPreviewing = false;
}

// 生成播客
async function podGenerate() {
  const script = document.getElementById('pod-script-editor')?.value || podcastState.script || '';
  if (!script.trim()) {
    toast('剧本不能为空', 'error');
    return;
  }
  // 重新收集音色映射（防止用户在步骤3修改后未触发 change）
  document.querySelectorAll('.pod-voice-select').forEach(sel => {
    const role = sel.dataset.role;
    if (sel.value) podcastState.voiceMap[role] = sel.value;
  });
  if (Object.keys(podcastState.voiceMap).length === 0) {
    toast('请先分配音色', 'error');
    return;
  }

  const outputName = (document.getElementById('pod-output-name')?.value || '').trim();

  // 收集 BGM 参数
  const bgmEnabled = document.getElementById('pod-bgm-enabled')?.checked || false;
  const bgmTrack = bgmEnabled ? (document.getElementById('pod-bgm-track')?.value || '') : '';
  const bgmVolume = bgmEnabled ? parseFloat(document.getElementById('pod-bgm-volume')?.value || '0.15') : 0.15;

  // 停止 BGM 试听（避免与生成冲突）
  stopPodcastBgmPreview();

  const btn = document.getElementById('pod-generate-btn');
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> 提交中...';
  if (window.lucide) lucide.createIcons();
  document.getElementById('pod-generate-section').style.display = 'none';
  document.getElementById('pod-progress-section').style.display = 'block';
  document.getElementById('pod-progress-bar').style.width = '0%';
  document.getElementById('pod-progress-text').textContent = '正在提交任务...';

  try {
    const reqBody = {
      script,
      voice_map: podcastState.voiceMap,
      output_name: outputName,
    };
    if (bgmTrack) {
      reqBody.bgm_track = bgmTrack;
      reqBody.bgm_volume = bgmVolume;
    }
    const data = await api('/api/podcast/generate', {
      method: 'POST',
      body: reqBody,
    });
    podcastState.jobId = data.job_id;
    // 开始轮询
    pollPodcastJob(data.job_id);
  } catch (e) {
    toast(`提交失败: ${e.message}`, 'error');
    document.getElementById('pod-generate-section').style.display = 'block';
    document.getElementById('pod-progress-section').style.display = 'none';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="rocket"></i> 开始生成播客';
    if (window.lucide) lucide.createIcons();
  }
}

// 轮询播客任务状态
function pollPodcastJob(jobId) {
  if (podcastState.pollTimer) clearInterval(podcastState.pollTimer);
  // 卡住检测：记录上次进度文本和更新时间
  let lastProgressMsg = '';
  let lastProgressTime = Date.now();
  const STUCK_THRESHOLD = 120000; // 120 秒进度无变化视为卡住

  podcastState.pollTimer = setInterval(async () => {
    try {
      const job = await api(`/api/podcast/jobs/${jobId}`);
      if (job.status === 'running' && job.progress) {
        const pct = job.progress.total > 0 ? (job.progress.current / job.progress.total * 100) : 0;
        document.getElementById('pod-progress-bar').style.width = pct + '%';
        const msg = job.progress.message || `进度 ${job.progress.current}/${job.progress.total}`;
        document.getElementById('pod-progress-text').textContent = msg;

        // 卡住检测：进度文本变化时重置计时器
        if (msg !== lastProgressMsg) {
          lastProgressMsg = msg;
          lastProgressTime = Date.now();
          document.getElementById('pod-stuck-warning').style.display = 'none';
        } else if (Date.now() - lastProgressTime > STUCK_THRESHOLD) {
          // 进度超过 120 秒没变化，显示卡住警告
          document.getElementById('pod-stuck-warning').style.display = 'block';
        }
      } else if (job.status === 'success') {
        clearInterval(podcastState.pollTimer);
        podcastState.pollTimer = null;
        podcastState.result = job.result;
        document.getElementById('pod-progress-bar').style.width = '100%';
        document.getElementById('pod-progress-text').textContent = '生成完成！';
        document.getElementById('pod-stuck-warning').style.display = 'none';
        setTimeout(() => showPodcastResult(job.result), 500);
      } else if (job.status === 'failed') {
        clearInterval(podcastState.pollTimer);
        podcastState.pollTimer = null;
        toast(`生成失败: ${job.error}`, 'error');
        document.getElementById('pod-progress-section').style.display = 'none';
        document.getElementById('pod-generate-section').style.display = 'block';
      } else if (job.status === 'cancelled') {
        clearInterval(podcastState.pollTimer);
        podcastState.pollTimer = null;
        toast('任务已取消', 'info');
        document.getElementById('pod-progress-section').style.display = 'none';
        document.getElementById('pod-generate-section').style.display = 'block';
      }
    } catch (e) {
      console.warn('轮询播客任务失败:', e.message);
    }
  }, 2000);
}

// 取消播客任务
async function cancelPodcastJob() {
  if (!podcastState.jobId) return;
  try {
    await api(`/api/podcast/jobs/${podcastState.jobId}/cancel`, { method: 'POST' });
    toast('正在取消任务...', 'info');
  } catch (e) {
    toast(`取消失败: ${e.message}`, 'error');
  }
}

// 显示生成结果
function showPodcastResult(result) {
  document.getElementById('pod-progress-section').style.display = 'none';
  document.getElementById('pod-result-section').style.display = 'block';
  // 音频播放器
  const audioPath = result.audio_path || '';
  const audioUrl = `/api/files?path=${encodeURIComponent(audioPath)}`;
  document.getElementById('pod-audio-player').src = audioUrl;
  // 统计
  document.getElementById('pod-result-duration').textContent = formatPodcastDuration(result.total_duration);
  document.getElementById('pod-result-segments').textContent = result.segment_count || 0;
  document.getElementById('pod-result-roles').textContent = Object.keys(podcastState.voiceMap).length;
  if (window.lucide) lucide.createIcons();
  // 提示（含 BGM 信息）
  const bgmTrack = result.bgm_track;
  if (bgmTrack) {
    const bgmInfo = podcastState.bgmList.find(b => b.id === bgmTrack);
    const bgmLabel = bgmInfo ? bgmInfo.label : bgmTrack;
    toast(`播客生成完成！已混入 BGM：${bgmLabel}`, 'success');
  } else {
    toast('播客生成完成！', 'success');
  }
}

// 格式化时长
function formatPodcastDuration(seconds) {
  if (!seconds) return '0s';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

// 下载播客文件
function downloadPodcastFile(filePath, filename) {
  if (!filePath) {
    toast('文件路径不存在', 'error');
    return;
  }
  const url = `/api/files?path=${encodeURIComponent(filePath)}`;
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
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
    setBtnIcon(btn, 'play', '执行 AI 处理');
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

let _batchMode = 'simple'; // 'simple' | 'matrix'

function switchBatchMode(mode) {
  _batchMode = mode;
  const simpleBtn = document.getElementById('batch-mode-simple');
  const matrixBtn = document.getElementById('batch-mode-matrix');
  const simpleFields = document.getElementById('batch-simple-fields');
  const matrixFields = document.getElementById('batch-matrix-fields');
  const hintSimple = document.getElementById('batch-mode-hint-simple');
  const hintMatrix = document.getElementById('batch-mode-hint-matrix');
  if (mode === 'matrix') {
    simpleBtn.className = 'btn btn-sm btn-secondary';
    matrixBtn.className = 'btn btn-sm btn-primary';
    simpleFields.style.display = 'none';
    matrixFields.style.display = '';
    hintSimple.style.display = 'none';
    hintMatrix.style.display = '';
    loadMatrixOptions();
    updateMatrixPreview();
  } else {
    simpleBtn.className = 'btn btn-sm btn-primary';
    matrixBtn.className = 'btn btn-sm btn-secondary';
    simpleFields.style.display = '';
    matrixFields.style.display = 'none';
    hintSimple.style.display = '';
    hintMatrix.style.display = 'none';
  }
}

async function loadMatrixOptions() {
  // 加载数字人和音色列表到矩阵 checkbox 网格
  const avatarsEl = document.getElementById('batch-matrix-avatars');
  const voicesEl = document.getElementById('batch-matrix-voices');
  if (!avatarsEl || !voicesEl) return;
  if (avatarsEl.children.length) return; // 已加载过
  try {
    const avatars = await api('/api/avatars');
    const avatarList = avatars.avatars || avatars || [];
    avatarsEl.innerHTML = avatarList.map(a => `
      <label class="matrix-checkbox-item">
        <input type="checkbox" value="${a.id || a.avatar_id || 'default'}" onchange="updateMatrixPreview()" ${a.id === 'default' ? 'checked' : ''}>
        <span>${a.name || a.id || 'default'}</span>
      </label>
    `).join('') || '<div class="hint">无可用数字人</div>';

    const voices = await api('/api/voices');
    const voiceList = voices.voices || voices || [];
    voicesEl.innerHTML = voiceList.map(v => `
      <label class="matrix-checkbox-item">
        <input type="checkbox" value="${v.id || v.voice_id || 'default'}" onchange="updateMatrixPreview()" ${v.id === 'default' ? 'checked' : ''}>
        <span>${v.name || v.id || 'default'}</span>
      </label>
    `).join('') || '<div class="hint">无可用音色</div>';
  } catch (e) {
    avatarsEl.innerHTML = `<div class="hint">加载失败: ${e.message}</div>`;
    voicesEl.innerHTML = `<div class="hint">加载失败: ${e.message}</div>`;
  }
}

function updateMatrixPreview() {
  const preview = document.getElementById('batch-matrix-preview');
  if (!preview) return;
  const avatars = Array.from(document.querySelectorAll('#batch-matrix-avatars input:checked')).map(c => c.value);
  const voices = Array.from(document.querySelectorAll('#batch-matrix-voices input:checked')).map(c => c.value);
  const scriptsText = document.getElementById('batch-scripts').value.trim();
  const scriptCount = scriptsText ? scriptsText.split(/\n\s*\n/).filter(s => s.trim()).length : 0;
  const total = avatars.length * voices.length * Math.max(scriptCount, 1);
  preview.textContent = `已选 ${avatars.length} 形象 × ${voices.length} 音色 × ${scriptCount || 1} 文案 = 共 ${total} 个视频变体`;
}

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

  const mode = document.getElementById('batch-mode').value;
  const platform = document.getElementById('batch-platform').value;

  // 矩阵模式
  if (_batchMode === 'matrix') {
    await handleMatrixGenerate(scripts, mode, platform);
    return;
  }

  // 普通批量模式（原有逻辑）
  const avatar = document.getElementById('batch-avatar').value;
  const voice = document.getElementById('batch-voice').value;

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
          itemEl.querySelector('.batch-item-meta').innerHTML = `<i data-lucide="check-circle"></i> 成功 · ${videoPath ? `<a href="/api/files?path=${encodeURIComponent(videoPath)}" target="_blank">查看视频</a>` : ''}`;
          if (window.lucide) lucide.createIcons();
        } else {
          itemEl.classList.remove('running');
          itemEl.classList.add('failed');
          itemEl.querySelector('.batch-item-meta').innerHTML = `<i data-lucide="x-circle"></i> 失败: ${escapeHtml(result.error || '未知错误')}`;
          if (window.lucide) lucide.createIcons();
        }
      } catch (e) {
        itemEl.classList.remove('running');
        itemEl.classList.add('failed');
        itemEl.querySelector('.batch-item-meta').innerHTML = `<i data-lucide="x-circle"></i> 异常: ${escapeHtml(e.message)}`;
        if (window.lucide) lucide.createIcons();
      }
    }

    const successCount = document.querySelectorAll('.batch-item.success').length;
    toast(`批量完成：${successCount}/${scripts.length} 成功`, successCount === scripts.length ? 'success' : 'info');
  } catch (e) {
    toast(`批量处理失败: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    setBtnIcon(btn, 'package', '开始批量生成');
  }
}

// 矩阵生成（对标万兴播爆批量裂变）
async function handleMatrixGenerate(scripts, mode, platform) {
  const avatarIds = Array.from(document.querySelectorAll('#batch-matrix-avatars input:checked')).map(c => c.value);
  const voiceIds = Array.from(document.querySelectorAll('#batch-matrix-voices input:checked')).map(c => c.value);
  const parallel = parseInt(document.getElementById('batch-matrix-parallel').value);

  if (!avatarIds.length) { toast('请至少选择一个数字人', 'error'); return; }
  if (!voiceIds.length) { toast('请至少选择一个音色', 'error'); return; }

  const btn = document.getElementById('batch-run-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 矩阵生成中...';

  const listEl = document.getElementById('batch-progress-list');
  const badgeEl = document.getElementById('batch-progress-badge');

  // 对每条文案提交矩阵生成
  let allJobIds = [];
  let allMatrixMeta = [];
  for (const script of scripts) {
    try {
      const result = await api('/api/batch/matrix', {
        method: 'POST',
        body: {
          script, avatar_ids: avatarIds, voice_ids: voiceIds,
          script_mode: mode, platform, auto_publish: false, parallel,
        },
      });
      if (result.success) {
        allJobIds = allJobIds.concat(result.job_ids);
        allMatrixMeta = allMatrixMeta.concat(result.matrix.map(m => ({...m, script: script.substring(0, 40)})));
      }
    } catch (e) {
      toast(`矩阵提交失败: ${e.message}`, 'error');
      btn.disabled = false;
      setBtnIcon(btn, 'package', '开始批量生成');
      return;
    }
  }

  const total = allJobIds.length;
  badgeEl.textContent = `0 / ${total}`;
  listEl.innerHTML = allMatrixMeta.map((m, i) => `
    <div class="batch-item" id="batch-item-${i}">
      <div class="batch-item-index">${i + 1}</div>
      <div class="batch-item-content">
        <div class="batch-item-text">${escapeHtml(m.avatar_id)} × ${escapeHtml(m.voice_id)}${m.script ? ' · ' + escapeHtml(m.script) : ''}</div>
        <div class="batch-item-meta">排队中...</div>
      </div>
    </div>
  `).join('');

  // 轮询每个 job 状态
  let completed = 0;
  const pollInterval = setInterval(async () => {
    for (let i = 0; i < allJobIds.length; i++) {
      const itemEl = document.getElementById(`batch-item-${i}`);
      if (!itemEl || itemEl.classList.contains('success') || itemEl.classList.contains('failed')) continue;
      try {
        const job = await api(`/api/jobs/${allJobIds[i]}`);
        const status = job.status || 'pending';
        if (status === 'running') {
          if (!itemEl.classList.contains('running')) {
            itemEl.classList.add('running');
            const step = job.current_step || job.steps?.find(s => s.status === 'running')?.name || '';
            itemEl.querySelector('.batch-item-meta').textContent = step ? `执行中: ${step}` : '生成中...';
          }
        } else if (status === 'success' || status === 'completed') {
          itemEl.classList.remove('running');
          itemEl.classList.add('success');
          const videoPath = job.video_path || job.output?.final_video || '';
          itemEl.querySelector('.batch-item-meta').innerHTML = `<i data-lucide="check-circle"></i> 成功 ${videoPath ? `· <a href="/api/files?path=${encodeURIComponent(videoPath)}" target="_blank">查看</a>` : ''}`;
          if (window.lucide) lucide.createIcons();
          completed++;
          badgeEl.textContent = `${completed} / ${total}`;
        } else if (status === 'failed' || status === 'error') {
          itemEl.classList.remove('running');
          itemEl.classList.add('failed');
          itemEl.querySelector('.batch-item-meta').innerHTML = `<i data-lucide="x-circle"></i> 失败: ${escapeHtml(job.error || '未知')}`;
          if (window.lucide) lucide.createIcons();
          completed++;
          badgeEl.textContent = `${completed} / ${total}`;
        }
      } catch (e) {}
    }
    if (completed >= total) {
      clearInterval(pollInterval);
      const successCount = document.querySelectorAll('.batch-item.success').length;
      toast(`矩阵完成：${successCount}/${total} 成功`, successCount === total ? 'success' : 'info');
      btn.disabled = false;
      setBtnIcon(btn, 'package', '开始批量生成');
    }
  }, 2000);
}

// ========== 初始化 ==========

document.addEventListener('DOMContentLoaded', () => {
  // 初始化 Lucide 矢量图标（替换全站 Emoji，专业图标系统）
  if (window.lucide) lucide.createIcons();

  // 导航绑定
  PAGES.forEach(p => {
    const nav = document.getElementById(`nav-${p}`);
    if (nav) nav.addEventListener('click', () => navigate(p));
  });

  // 资源中心 / 设置中心 分组导航绑定
  document.getElementById('nav-resources')?.addEventListener('click', () => navigate('avatars'));
  document.getElementById('nav-settings')?.addEventListener('click', () => navigate('settings-models'));

  // 向导步骤6：跳转到发布设置页
  document.getElementById('wiz-goto-publish-settings')?.addEventListener('click', (e) => {
    e.preventDefault();
    navigate('settings-publish');
  });

  // 资源中心 / 设置中心 内部 Tab 点击切换（事件委托）
  document.addEventListener('click', (e) => {
    const rt = e.target.closest('.resource-tab');
    if (rt) { navigate(rt.dataset.target); return; }
    const st = e.target.closest('.settings-tab');
    if (st) navigate(st.dataset.target);
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

  // 联动 P3：自动发布开关——开启时校验登录态，未登录平台即时提示
  document.getElementById('wiz-auto-publish')?.addEventListener('change', (e) => {
    const platformsBox = document.getElementById('wiz-publish-platforms');
    const checked = Array.from(document.querySelectorAll('#wiz-publish-platforms input[type="checkbox"]:checked')).length;
    if (e.target.checked) {
      if (platformsBox && checked === 0) {
        platformsBox.style.boxShadow = '0 0 0 3px var(--color-warning)';
        toast('请选择至少一个发布平台', 'info');
      } else {
        // 联动 P3：检查选中平台中是否有未登录的
        const unlogged = getWizUnloggedPlatforms();
        if (unlogged.length > 0) {
          const names = unlogged.map(p => WIZ_PLATFORM_INFO[p]?.name || p).join('、');
          platformsBox.style.boxShadow = '0 0 0 3px rgba(255,69,58,0.2)';
          toast(`以下平台未登录：${names}，将无法自动发布。点击"前往发布设置"登录`, 'warning');
        } else {
          platformsBox.style.boxShadow = '0 0 0 3px var(--state-success-light)';
        }
      }
    } else if (platformsBox) {
      platformsBox.style.boxShadow = '';
    }
  });
  // 联动 P3：平台选择变化时——勾选未登录平台即时提示
  document.getElementById('wiz-publish-platforms')?.addEventListener('change', (e) => {
    const autoPub = document.getElementById('wiz-auto-publish');
    const platformsBox = document.getElementById('wiz-publish-platforms');
    // 如果是勾选操作且该平台未登录，即时提示
    if (e.target.type === 'checkbox' && e.target.checked) {
      const platform = e.target.value;
      const status = window._wizPlatformLoginStatus[platform];
      if (!status || !status.success || !status.logged_in) {
        const name = WIZ_PLATFORM_INFO[platform]?.name || platform;
        toast(`${name} 未登录，自动发布将跳过此平台。请前往设置中心登录`, 'warning');
      }
    }
    // 更新高亮
    if (autoPub && autoPub.checked && platformsBox) {
      const checked = Array.from(document.querySelectorAll('#wiz-publish-platforms input[type="checkbox"]:checked')).length;
      const unlogged = getWizUnloggedPlatforms();
      if (checked === 0) {
        platformsBox.style.boxShadow = '0 0 0 3px var(--color-warning)';
      } else if (unlogged.length > 0) {
        platformsBox.style.boxShadow = '0 0 0 3px rgba(255,69,58,0.2)';
      } else {
        platformsBox.style.boxShadow = '0 0 0 3px var(--state-success-light)';
      }
    }
  });

  // 初始渲染进度
  renderPipeline({});

  // 默认落地页：创作向导
  navigate('wizard');
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
    const modeIcon = clip.mode === 'pip' ? '<i data-lucide="image"></i>' : '<i data-lucide="scissors"></i>';
    const transIcon = clip.transition === 'fade' ? ' <i data-lucide="contrast"></i>' : '';
    seg.innerHTML = `${modeIcon}${transIcon} ${clip.filename || 'B-roll'}<span class="tl-segment-delete" onclick="event.stopPropagation();deleteClip(${idx})">×</span>`;
    seg.title = `${clip.mode === 'pip' ? '画中画' : '整段切换'} · ${clip.start}s-${clip.end}s · 点击编辑`;
    seg.onclick = (e) => {
      e.stopPropagation();
      openClipModalForEdit(idx);
    };
    brollTrack.appendChild(seg);
  });
  if (window.lucide) lucide.createIcons();

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
    const iconName = a.kind === 'video' ? 'film' : 'image';
    const thumb = a.kind === 'image'
      ? `<img src="/api/broll/assets/${encodeURIComponent(a.filename)}" onerror="setFallbackIcon(this.parentElement,'${iconName}')">`
      : `<i data-lucide="${iconName}"></i>`;
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
  if (window.lucide) lucide.createIcons();
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
  fillTlSubtitleSegs();
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
  fillTlSubtitleSegs();
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

// 填充时间轴编辑器弹窗的字幕段落下拉
function fillTlSubtitleSegs() {
  const sel = document.getElementById('clip-subtitle-seg');
  if (!sel) return;
  const segs = tlState.subtitleSegments || [];
  sel.innerHTML = '<option value="-1">自定义时间</option>';
  segs.forEach((seg, i) => {
    const text = (seg.text || '').substring(0, 20);
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `第${i + 1}句 (${seg.start.toFixed(1)}-${seg.end.toFixed(1)}s)${text ? ': ' + text : ''}`;
    sel.appendChild(opt);
  });
}

// 时间轴编辑器弹窗字幕段落选择联动
function onTlSubtitleSegChange(idx) {
  if (idx === '-1' || idx === -1) return;
  const segs = tlState.subtitleSegments || [];
  const seg = segs[parseInt(idx)];
  if (!seg) return;
  document.getElementById('clip-start').value = seg.start.toFixed(1);
  document.getElementById('clip-end').value = seg.end.toFixed(1);
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
        <span class="clip-edit" onclick="openClipModalForEdit(${idx})" title="编辑"><i data-lucide="pencil"></i></span>
        <span class="clip-delete" onclick="deleteClip(${idx})" title="删除"><i data-lucide="trash-2"></i></span>
      </div>
    `;
  }).join('');
  if (window.lucide) lucide.createIcons();
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

// ============ B-roll 智能插入（对标剪映智能匹配素材） ============

let _brollSuggestions = []; // AI 推荐结果缓存

async function suggestBrollClips() {
  const jobId = document.getElementById('tl-job-select')?.value;
  if (!jobId) { toast('请先选择任务', 'error'); return; }
  const btn = document.getElementById('tl-suggest-btn');
  const panel = document.getElementById('tl-suggest-panel');
  const list = document.getElementById('tl-suggest-list');
  if (!btn || !panel || !list) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> AI 分析中...';
  panel.style.display = 'block';
  list.innerHTML = '<div style="color:#666;font-size:13px;padding:8px">AI 正在分析文案与字幕，匹配 B-roll 素材...</div>';
  try {
    const result = await api('/api/broll/suggest', {
      method: 'POST',
      body: { job_id: jobId, max_clips: 5 },
    });
    if (!result.success) {
      list.innerHTML = `<div style="color:#c0392b;font-size:13px;padding:8px">推荐失败：${result.error || '未知错误'}</div>`;
      return;
    }
    _brollSuggestions = result.suggestions || [];
    renderBrollSuggestions(result.meta);
  } catch (e) {
    list.innerHTML = `<div style="color:#c0392b;font-size:13px;padding:8px">请求失败：${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="sparkles"></i> 智能插入';
    if (window.lucide) lucide.createIcons();
  }
}

function renderBrollSuggestions(meta) {
  const list = document.getElementById('tl-suggest-list');
  if (!_brollSuggestions.length) {
    list.innerHTML = '<div style="color:#666;font-size:13px;padding:8px">AI 未找到合适的 B-roll 插入点，请尝试上传更多相关素材</div>';
    return;
  }
  const metaText = meta ? `（文案 ${meta.script_length} 字 · 字幕 ${meta.subtitle_count} 段 · 素材 ${meta.asset_count} 个 · 时长 ${meta.video_duration.toFixed(1)}s）` : '';
  list.innerHTML = _brollSuggestions.map((s, i) => {
    const modeLabel = s.mode === 'cut' ? '整段切换' : '画中画';
    const modeColor = s.mode === 'cut' ? '#e74c3c' : '#3498db';
    return `
      <div class="broll-suggest-card" data-idx="${i}" style="background:#fff;border:1px solid #d0e0f0;border-radius:6px;padding:10px;display:flex;gap:10px;align-items:flex-start">
        <div style="flex:1">
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap">
            <span style="font-weight:600;font-size:13px;color:#1a4d8f">${s.filename}</span>
            <span style="font-size:11px;padding:1px 6px;border-radius:3px;background:${modeColor};color:#fff">${modeLabel}</span>
            <span style="font-size:11px;color:#666">${s.start}s - ${s.end}s（${(s.end-s.start).toFixed(1)}s）</span>
          </div>
          <div style="font-size:12px;color:#555;line-height:1.5">${s.reason || 'AI 推荐插入点'}</div>
        </div>
        <button class="btn btn-sm btn-primary" onclick="acceptBrollSuggestion(${i})">接受</button>
      </div>
    `;
  }).join('') + `<div style="font-size:11px;color:#888;margin-top:4px">${metaText}</div>`;
}

function acceptBrollSuggestion(idx) {
  const s = _brollSuggestions[idx];
  if (!s) return;
  // 转换为 clips 格式并追加到 tlState.clips
  const clip = {
    path: s.path,
    filename: s.filename,
    start: s.start,
    end: s.end,
    mode: s.mode,
    position: s.position || 'top_right',
    scale: s.scale || 0.35,
    volume: s.volume ?? 0,
    transition: s.transition || 'fade',
  };
  tlState.clips.push(clip);
  // 从推荐列表移除
  _brollSuggestions.splice(idx, 1);
  renderBrollSuggestions();
  renderTimeline();
  renderClipList();
  toast('已接受推荐并添加到片段列表', 'success');
}

function acceptAllBrollSuggestions() {
  if (!_brollSuggestions.length) return;
  let count = 0;
  _brollSuggestions.forEach(s => {
    tlState.clips.push({
      path: s.path,
      filename: s.filename,
      start: s.start,
      end: s.end,
      mode: s.mode,
      position: s.position || 'top_right',
      scale: s.scale || 0.35,
      volume: s.volume ?? 0,
      transition: s.transition || 'fade',
    });
    count++;
  });
  _brollSuggestions = [];
  renderBrollSuggestions();
  renderTimeline();
  renderClipList();
  toast(`已接受全部 ${count} 个推荐`, 'success');
}

function clearBrollSuggestions() {
  _brollSuggestions = [];
  document.getElementById('tl-suggest-panel').style.display = 'none';
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
  const titles = { trim: '<i data-lucide="scissors"></i> 裁剪视频', volume: '<i data-lucide="volume-2"></i> 调整音量', fade: '<i data-lucide="contrast"></i> 淡入淡出' };
  document.getElementById('qe-title').innerHTML = titles[action] || '快捷剪辑';
  if (window.lucide) lucide.createIcons();
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

// ========== 创作向导 B-roll 集成 ==========
let wizBrollState = {
  assets: [],        // 素材库
  clips: [],         // 已添加片段
  selectedAsset: null,
  duration: 60,      // 默认时长（生成后会更新）
  subtitleSegments: []  // 字幕时间段
};

// 开关 B-roll 面板
function toggleWizardBroll() {
  const enabled = document.getElementById('wiz-broll-enabled').checked;
  document.getElementById('wiz-broll-group').style.display = enabled ? 'block' : 'none';
  if (enabled) {
    loadWizardBrollAssets();
    // 自动从文案加载字幕时间轴（对标商业口播智能体：启用即可见字幕段落）
    autoLoadWizardSubtitles();
    renderWizardTimeline();
  }
}

// 自动从文案预估字幕时间轴（无需用户手动点击"智能推荐"）
function autoLoadWizardSubtitles() {
  const script = document.getElementById('wiz-script')?.value || document.getElementById('wizard-script')?.value || '';
  if (!script.trim()) {
    return; // 无文案时不生成
  }
  const sentences = script.split(/[。！？\n]/).filter(s => s.trim().length > 2);
  if (!sentences.length) return;
  let currentTime = 1.5; // 字幕从1.5s开始（跳过封面段）
  wizBrollState.subtitleSegments = sentences.map(s => {
    const dur = Math.max(2, s.length * 0.35);
    const seg = { text: s.trim(), start: currentTime, end: currentTime + dur };
    currentTime += dur + 0.2;
    return seg;
  });
  wizBrollState.duration = currentTime + 1;
}

// 加载 B-roll 素材库
async function loadWizardBrollAssets() {
  try {
    const assets = await api('/api/broll/assets');
    wizBrollState.assets = assets || [];
  } catch (e) {
    wizBrollState.assets = [];
  }
  renderWizardBrollList();
}

// 渲染素材列表
function renderWizardBrollList() {
  const list = document.getElementById('wiz-broll-list');
  if (!list) return;
  if (!wizBrollState.assets.length) {
    list.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:12px;text-align:center;width:100%">暂无素材，请上传</div>';
    return;
  }
  list.innerHTML = wizBrollState.assets.map(a => {
    const sizeStr = a.size > 1024*1024 ? (a.size/1024/1024).toFixed(1)+'MB' : Math.max(1,Math.round(a.size/1024))+'KB';
    const isVideo = a.kind === 'video';
    const thumb = isVideo
      ? `<video src="/api/broll/assets/${encodeURIComponent(a.filename)}" muted preload="metadata"></video>`
      : `<img src="/api/broll/assets/${encodeURIComponent(a.filename)}" onerror="this.style.display='none'">`;
    return `
      <div class="broll-asset-card ${wizBrollState.selectedAsset?.path === a.path ? 'selected' : ''}"
           style="width:calc(50% - 4px);cursor:pointer"
           onclick="selectWizardBrollAsset('${a.path.replace(/\\/g,'\\\\')}')">
        <div class="broll-asset-thumb">${thumb}</div>
        <div class="broll-asset-info">
          <div class="broll-asset-name" style="font-size:11px">${a.filename}</div>
          <div class="broll-asset-meta">${a.kind === 'video' ? '视频' : '图片'} · ${sizeStr}</div>
        </div>
      </div>`;
  }).join('');
}

// 选择素材
function selectWizardBrollAsset(path) {
  wizBrollState.selectedAsset = wizBrollState.assets.find(a => a.path.replace(/\\/g,'\\\\') === path || a.path === path);
  renderWizardBrollList();
  toast('已选择素材：' + (wizBrollState.selectedAsset?.filename || ''), 'info');
}

// 上传 B-roll 素材
async function onWizardBrollUpload(input) {
  const file = input.files[0];
  if (!file) return;
  toast('上传中...', 'info');
  const formData = new FormData();
  formData.append('file', file);
  try {
    const resp = await fetch('/api/broll/upload', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.success) {
      toast('上传成功：' + data.filename, 'success');
      await loadWizardBrollAssets();
    } else {
      toast('上传失败', 'error');
    }
  } catch (e) {
    toast('上传失败：' + e.message, 'error');
  }
  input.value = '';
}

// 智能推荐 B-roll（刷新字幕时间轴）
async function wizardBrollSuggest() {
  const script = document.getElementById('wiz-script')?.value || '';
  if (!script.trim()) {
    toast('请先在步骤3输入文案', 'warning');
    return;
  }
  autoLoadWizardSubtitles();
  renderWizardTimeline();
  if (wizBrollState.subtitleSegments.length) {
    toast(`已基于文案预估 ${wizBrollState.subtitleSegments.length} 段字幕时间轴，点击段落卡片可插入 B-roll`, 'success');
  } else {
    toast('无法从文案提取句子，请检查文案内容', 'warning');
  }
}

// 渲染时间轴
function renderWizardTimeline() {
  const track = document.getElementById('wiz-broll-track');
  const subTrack = document.getElementById('wiz-subtitle-track');
  const ruler = document.getElementById('wiz-ruler');
  if (!track || !subTrack) return;

  const duration = wizBrollState.duration || 60;
  const trackWidth = Math.max(600, duration * 20);

  track.style.width = trackWidth + 'px';
  subTrack.style.width = trackWidth + 'px';
  if (ruler) {
    ruler.style.width = trackWidth + 'px';
    ruler.innerHTML = '';
    for (let t = 0; t <= duration; t += Math.max(1, Math.round(duration / 20))) {
      const tick = document.createElement('div');
      tick.className = 'ruler-tick';
      tick.style.left = (t * 20) + 'px';
      tick.textContent = t + 's';
      ruler.appendChild(tick);
    }
  }

  track.innerHTML = '';
  track.onclick = (e) => {
    if (e.target !== track) return;
    if (!wizBrollState.selectedAsset) {
      toast('请先在左侧选择一个 B-roll 素材', 'error');
      return;
    }
    const rect = track.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const start = x / 20;
    openWizardClipModal(start);
  };

  wizBrollState.clips.forEach((clip, idx) => {
    const seg = document.createElement('div');
    seg.className = `tl-broll-segment ${clip.mode}`;
    seg.style.left = (clip.start * 20) + 'px';
    seg.style.width = ((clip.end - clip.start) * 20) + 'px';
    const modeIcon = clip.mode === 'pip' ? 'PIP' : 'CUT';
    seg.innerHTML = `${modeIcon} ${clip.filename || 'B-roll'}<span class="tl-segment-delete" onclick="event.stopPropagation();deleteWizardClip(${idx})">×</span>`;
    seg.title = `${clip.mode === 'pip' ? '画中画' : '整段切换'} · ${clip.start.toFixed(1)}s-${clip.end.toFixed(1)}s · 点击编辑`;
    seg.onclick = (e) => { e.stopPropagation(); openWizardClipModal(null, idx); };
    track.appendChild(seg);
  });

  subTrack.innerHTML = '';
  if (!wizBrollState.subtitleSegments.length) {
    subTrack.innerHTML = '<div style="color:var(--text-tertiary);font-size:11px;padding:0 8px;line-height:32px">暂无字幕数据（可点击B-roll轨道空白处插入）</div>';
  } else {
    wizBrollState.subtitleSegments.forEach((seg, idx) => {
      const el = document.createElement('div');
      el.className = 'tl-subtitle-segment';
      el.style.left = (seg.start * 20) + 'px';
      el.style.width = ((seg.end - seg.start) * 20) + 'px';
      el.textContent = seg.text.length > 12 ? seg.text.slice(0, 12) + '…' : seg.text;
      el.title = `${seg.start.toFixed(1)}s-${seg.end.toFixed(1)}s: ${seg.text}`;
      subTrack.appendChild(el);

      if (idx < wizBrollState.subtitleSegments.length - 1) {
        const nextStart = wizBrollState.subtitleSegments[idx + 1].start;
        const gapStart = seg.end;
        const gapEnd = nextStart;
        if (gapEnd - gapStart > 0.3) {
          const insertBtn = document.createElement('div');
          insertBtn.className = 'tl-insert-plus';
          insertBtn.style.left = (((gapStart + gapEnd) / 2) * 20 - 9) + 'px';
          insertBtn.textContent = '+';
          insertBtn.title = `在字幕间插入 B-roll（${gapStart.toFixed(1)}s - ${gapEnd.toFixed(1)}s 间隙）`;
          insertBtn.onclick = (e) => {
            e.stopPropagation();
            if (!wizBrollState.selectedAsset) {
              toast('请先选择一个 B-roll 素材', 'error');
              return;
            }
            openWizardClipModal(gapStart, null, gapEnd);
          };
          subTrack.appendChild(insertBtn);
        }
      }
    });
  }
  // 渲染垂直字幕段落列表
  renderWizardSubtitleList();
}

// 渲染垂直字幕段落列表（对标商业口播智能体）
function renderWizardSubtitleList() {
  const container = document.getElementById('wiz-subtitle-list');
  if (!container) return;
  const segs = wizBrollState.subtitleSegments || [];
  if (!segs.length) {
    container.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:12px;text-align:center">暂无字幕数据，请在步骤3输入文案后自动生成<br>或点击"智能推荐"刷新</div>';
    return;
  }
  container.innerHTML = segs.map((seg, idx) => {
    const hasClip = wizBrollState.clips.some(c => c.start >= seg.start - 0.5 && c.start < seg.end);
    const clipBadge = hasClip ? '<span style="background:var(--color-success);color:#fff;font-size:10px;padding:1px 6px;border-radius:4px;margin-left:6px">已插入</span>' : '';
    const dur = (seg.end - seg.start).toFixed(1);
    return `
      <div style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;cursor:pointer;transition:border-color 0.2s"
           onmouseover="this.style.borderColor='var(--color-primary)'"
           onmouseout="this.style.borderColor='var(--border-default)'"
           onclick="if(wizBrollState.selectedAsset){openWizardClipModal(${seg.start}, null, ${seg.end})}else{toast('请先选择一个 B-roll 素材','error')}">
        <div style="flex-shrink:0;width:36px;height:36px;background:var(--color-primary);color:#fff;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:600">${idx + 1}</div>
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;margin-bottom:4px">
            <span style="font-size:12px;color:var(--text-secondary);font-family:var(--font-mono)">${seg.start.toFixed(1)}s - ${seg.end.toFixed(1)}s</span>
            <span style="font-size:11px;color:var(--text-tertiary);margin-left:6px">· ${dur}s</span>
            ${clipBadge}
          </div>
          <div style="font-size:13px;color:var(--text-primary);line-height:1.4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(seg.text)}</div>
        </div>
        <div style="flex-shrink:0;display:flex;align-items:center;color:var(--text-tertiary)">
          <i data-lucide="plus-circle" style="width:18px;height:18px"></i>
        </div>
      </div>`;
  }).join('');
  if (window.lucide) lucide.createIcons();
}

// 打开添加/编辑片段弹窗
function openWizardClipModal(start, editIdx, maxEnd) {
  const isEdit = editIdx !== null && editIdx !== undefined;
  const existing = isEdit ? wizBrollState.clips[editIdx] : null;
  const clip = isEdit ? existing : {
    start: start || 0,
    end: (start || 0) + 5,
    mode: 'pip',
    asset_path: wizBrollState.selectedAsset?.path || '',
    filename: wizBrollState.selectedAsset?.filename || '',
    transition: 'none',
    pip_position: 'bottom_right',
    pip_scale: 0.3
  };

  const overlay = document.createElement('div');
  overlay.className = 'wiz-clip-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(8px);z-index:9999;display:flex;align-items:center;justify-content:center';
  const modal = document.createElement('div');
  modal.className = 'glass-card-heavy';
  modal.style.cssText = 'width:400px;max-width:90vw;padding:24px;position:relative;background:var(--bg-surface,#fff);border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.18)';
  modal.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h3 style="font-size:18px;font-weight:600;margin:0">${isEdit ? '编辑' : '添加'} B-roll 片段</h3>
      <button type="button" onclick="this.closest('.wiz-clip-overlay').remove()" style="background:rgba(0,0,0,0.1);border:none;font-size:20px;color:var(--text-primary);cursor:pointer;padding:4px 10px;line-height:1;border-radius:6px;transition:background 0.2s" onmouseover="this.style.background='rgba(0,0,0,0.2)'" onmouseout="this.style.background='rgba(0,0,0,0.1)'">✕</button>
    </div>
    <div style="margin-bottom:12px">
      <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">素材</label>
      <div style="padding:8px 12px;background:var(--bg-elevated);border-radius:8px;font-size:13px">${clip.filename || '未选择'}</div>
    </div>
    <div style="margin-bottom:12px">
      <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">按字幕段落选择位置</label>
      <select id="wiz-clip-subtitle-seg" onchange="onWizardSubtitleSegChange(this.value)" style="width:100%;padding:8px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary);font-size:13px">
        <option value="-1">自定义时间</option>
      </select>
    </div>
    <div style="display:flex;gap:12px;margin-bottom:12px">
      <div style="flex:1">
        <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">开始(s)</label>
        <input type="number" id="wiz-clip-start" value="${clip.start.toFixed(1)}" step="0.5" min="0" style="width:100%;padding:8px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary)" oninput="document.getElementById('wiz-clip-subtitle-seg').value='-1'">
      </div>
      <div style="flex:1">
        <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">结束(s)</label>
        <input type="number" id="wiz-clip-end" value="${clip.end.toFixed(1)}" step="0.5" min="0" style="width:100%;padding:8px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary)" oninput="document.getElementById('wiz-clip-subtitle-seg').value='-1'">
      </div>
    </div>
    <div style="margin-bottom:12px">
      <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">模式</label>
      <select id="wiz-clip-mode" style="width:100%;padding:8px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary)" onchange="document.getElementById('wiz-pip-settings').style.display=this.value==='pip'?'block':'none'">
        <option value="pip" ${clip.mode==='pip'?'selected':''}>画中画(PIP) - 叠加在数字人上</option>
        <option value="cut" ${clip.mode==='cut'?'selected':''}>整段切换(CUT) - 替换主画面</option>
      </select>
    </div>
    <div id="wiz-pip-settings" style="display:${clip.mode==='pip'?'block':'none'};margin-bottom:12px">
      <div style="display:flex;gap:12px">
        <div style="flex:1">
          <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">位置</label>
          <select id="wiz-clip-pip-pos" style="width:100%;padding:6px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary)">
            <option value="bottom_right" ${clip.pip_position==='bottom_right'?'selected':''}>右下</option>
            <option value="bottom_left" ${clip.pip_position==='bottom_left'?'selected':''}>左下</option>
            <option value="top_right" ${clip.pip_position==='top_right'?'selected':''}>右上</option>
            <option value="top_left" ${clip.pip_position==='top_left'?'selected':''}>左上</option>
          </select>
        </div>
        <div style="flex:1">
          <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">缩放</label>
          <input type="range" id="wiz-clip-pip-scale" min="0.15" max="0.6" step="0.05" value="${clip.pip_scale||0.3}" style="width:100%">
        </div>
      </div>
    </div>
    <div style="margin-bottom:16px">
      <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px">转场</label>
      <select id="wiz-clip-trans" style="width:100%;padding:8px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary)">
        <option value="none" ${clip.transition==='none'?'selected':''}>无</option>
        <option value="fade" ${clip.transition==='fade'?'selected':''}>淡入淡出</option>
        <option value="slide" ${clip.transition==='slide'?'selected':''}>滑入</option>
        <option value="zoom" ${clip.transition==='zoom'?'selected':''}>缩放</option>
      </select>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      ${isEdit ? '<button class="btn btn-secondary" style="color:var(--state-error)" onclick="deleteWizardClip('+editIdx+');this.closest(\'.wiz-clip-overlay\').remove()">删除</button>' : ''}
      <button class="btn btn-secondary" onclick="this.closest('.wiz-clip-overlay').remove()">取消</button>
      <button class="btn btn-primary" onclick="saveWizardClip(${isEdit ? editIdx : 'null'})">保存</button>
    </div>
  `;
  overlay.appendChild(modal);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);
  // 填充字幕段落选项
  fillWizardSubtitleSegs();
}

// 填充Wizard弹窗的字幕段落下拉
function fillWizardSubtitleSegs() {
  const sel = document.getElementById('wiz-clip-subtitle-seg');
  if (!sel) return;
  const segs = wizBrollState.subtitleSegments || [];
  // 保留"自定义"选项，清空其余
  sel.innerHTML = '<option value="-1">自定义时间</option>';
  segs.forEach((seg, i) => {
    const text = (seg.text || '').substring(0, 20);
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `第${i + 1}句 (${seg.start.toFixed(1)}-${seg.end.toFixed(1)}s)${text ? ': ' + text : ''}`;
    sel.appendChild(opt);
  });
}

// Wizard弹窗字幕段落选择联动
function onWizardSubtitleSegChange(idx) {
  if (idx === '-1' || idx === -1) return;
  const segs = wizBrollState.subtitleSegments || [];
  const seg = segs[parseInt(idx)];
  if (!seg) return;
  const startEl = document.getElementById('wiz-clip-start');
  const endEl = document.getElementById('wiz-clip-end');
  if (startEl) startEl.value = seg.start.toFixed(1);
  if (endEl) endEl.value = seg.end.toFixed(1);
}

// 保存片段
function saveWizardClip(editIdx) {
  const start = parseFloat(document.getElementById('wiz-clip-start').value);
  const end = parseFloat(document.getElementById('wiz-clip-end').value);
  const mode = document.getElementById('wiz-clip-mode').value;
  const transition = document.getElementById('wiz-clip-trans').value;
  const pipPos = document.getElementById('wiz-clip-pip-pos')?.value || 'bottom_right';
  const pipScale = parseFloat(document.getElementById('wiz-clip-pip-scale')?.value || 0.3);

  if (end <= start) {
    toast('结束时间必须大于开始时间', 'error');
    return;
  }

  const existing = (editIdx !== null && editIdx !== undefined) ? wizBrollState.clips[editIdx] : null;
  const clip = {
    start, end, mode, transition,
    asset_path: wizBrollState.selectedAsset?.path || (existing?.asset_path || ''),
    filename: wizBrollState.selectedAsset?.filename || (existing?.filename || ''),
    pip_position: pipPos,
    pip_scale: pipScale
  };

  if (editIdx !== null && editIdx !== undefined) {
    wizBrollState.clips[editIdx] = clip;
  } else {
    wizBrollState.clips.push(clip);
  }

  document.querySelector('.wiz-clip-overlay')?.remove();
  renderWizardTimeline();
  renderWizardClipList();
  toast(`已${editIdx !== null ? '更新' : '添加'} ${mode === 'pip' ? '画中画' : '整段切换'} 片段 (${start.toFixed(1)}s-${end.toFixed(1)}s)`, 'success');
}

// 删除片段
function deleteWizardClip(idx) {
  wizBrollState.clips.splice(idx, 1);
  document.querySelector('.wiz-clip-overlay')?.remove();
  renderWizardTimeline();
  renderWizardClipList();
}

// 渲染已添加片段列表
function renderWizardClipList() {
  const list = document.getElementById('wiz-broll-clips');
  if (!list) return;
  if (!wizBrollState.clips.length) {
    list.innerHTML = '<div style="text-align:center;color:var(--text-tertiary);font-size:12px;padding:12px">暂无片段，点击时间轴添加</div>';
    return;
  }
  list.innerHTML = wizBrollState.clips.map((c, i) => `
    <div style="padding:8px 12px;background:var(--bg-elevated);border-radius:8px;margin-bottom:6px;font-size:12px;cursor:pointer" onclick="openWizardClipModal(null,${i})">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:500">${c.mode === 'pip' ? 'PIP' : 'CUT'} · ${c.filename || 'B-roll'}</span>
        <span style="color:var(--text-tertiary)">${c.start.toFixed(1)}-${c.end.toFixed(1)}s</span>
      </div>
    </div>
  `).join('');
}

// 清空所有片段
function clearWizardBrollClips() {
  if (!wizBrollState.clips.length) return;
  if (confirm('确定清空所有 B-roll 片段？')) {
    wizBrollState.clips = [];
    renderWizardTimeline();
    renderWizardClipList();
    toast('已清空', 'info');
  }
}

// 获取向导 B-roll 配置（供 wizardGenerate 调用）
function getWizardBrollClips() {
  if (!document.getElementById('wiz-broll-enabled')?.checked) return [];
  return wizBrollState.clips;
}


// 复制文本到剪贴板
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    toast('已复制到剪贴板', 'success');
  }).catch(() => {
    // 降级方案
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('已复制到剪贴板', 'success');
  });
}

// 打开任务工作目录（调用后端 /api/jobs/{job_id}/open-folder）
async function openJobFolder(jobId) {
  if (!jobId) {
    toast('缺少任务 ID', 'error');
    return;
  }
  try {
    const r = await api(`/api/jobs/${jobId}/open-folder`, { method: 'POST' });
    if (r.success) {
      toast('已打开任务目录', 'success');
    } else {
      toast('打开目录失败', 'error');
    }
  } catch (e) {
    toast(`打开目录失败: ${e.message}`, 'error');
  }
}
