// app.js — 应用入口（替代原 index.js 的 IIFE）

import { state, workspace } from './state.js';
import {
  loadResourceCatalog,
  loadResourcePage,
  loadStaticData,
  loadWorkspaces,
  loadWorkspaceMembers
} from './api.js';
import { render, injectStyles } from './render.js';
import { applyLocation, syncUrl } from './router.js';
import { handle, handleDebugInputKeydown, injectHandlerDeps, isComposerSendShortcut, loadPublishedChat, loadRuntimeRunDetail, updateChatAutoFollow, updateDebugAutoFollow } from './handler.js';
import { formatRuntimeElapsed } from './views/runtime-session.js';
import { loadCredentialPage } from './views/credentials.js';
import { loadEvolutionWorkspace, loadQualityOverview, loadRuntimeRuns } from './views/operations.js';
import { loadAgentMemory } from './views/agents.js';

const loadCredentialsAndRender = () => {
  const loading = loadCredentialPage();
  render();
  return loading.then(() => render());
};

// 注入 handler 所需的 go/toast/render 函数，避免循环依赖
const go = v => {
  if (state.view !== v) state.uiContextEpoch += 1;
  state.view = v;
  if (v === 'chat') state.chatAutoFollow = true;
  state.modal = '';
  syncUrl();
  const scopedLoading = v === 'resources' ? loadResourcePage(state.workspace)
    : v === 'evolution' ? loadEvolutionWorkspace()
    : v === 'quality' ? loadQualityOverview()
    : v === 'agent-detail' ? loadAgentMemory()
      : null;
  render();
  // 进入空间管理页时自动加载成员列表
  if (v === 'spaces') {
    const s = workspace();
    if (s) loadWorkspaceMembers(s.code).then(() => render()).catch(() => {});
  }
  if (v === 'chat') {
    return loadPublishedChat().then(() => render()).catch(error => {
      state.chatLoadError = error?.message || '会话加载失败';
      render();
    });
  }
  if (v === 'credentials') {
    return loadCredentialsAndRender();
  }
  if (['overview', 'my-tasks', 'runs'].includes(v)) return loadRuntimeRuns().then(() => render());
  if (scopedLoading) return Promise.resolve(scopedLoading).finally(() => render());
};
const toast = (message, type = '') => {
  const requestId = ++state.toastRequestId;
  state.toast = message;
  state.toastType = type;
  render();
  setTimeout(() => {
    if (requestId !== state.toastRequestId) return;
    state.toast = '';
    state.toastType = '';
    render();
  }, 3200);
};
injectHandlerDeps(go, toast, render);

// 注入全局样式
injectStyles();

// 事件委托：所有 data-view 和 data-action 点击
document.addEventListener('click', e => {
  const el = e.target.closest('[data-view],[data-action]');
  if (!el) return;
  if (el.dataset.view) return go(el.dataset.view);
  handle(el.dataset.action, el);
});

// 防抖搜索：监听带 data-debounce-action 的 input 事件
let _debounceTimer = null;
/**
 * 执行会触发整页重绘的输入操作，并恢复输入焦点、选区及弹窗滚动位置。
 * 筛选属于连续输入过程，只有用户主动点击其他控件时才应失焦。
 */
const handleDebouncedInput = el => {
  const shouldRestoreFocus = el.dataset.preserveFocus === 'true';
  const focusState = shouldRestoreFocus ? {
    id: el.id,
    start: el.selectionStart,
    end: el.selectionEnd,
    direction: el.selectionDirection,
    modalScrollTop: el.closest('.ap-modal')?.querySelector(':scope > div')?.scrollTop || 0
  } : null;
  const result = handle(el.dataset.debounceAction, el);
  if (!focusState) return;
  const restoreFocus = () => {
    const next = document.getElementById(focusState.id);
    if (!next) return;
    next.focus({ preventScroll: true });
    next.setSelectionRange(focusState.start, focusState.end, focusState.direction);
    const modalBody = next.closest('.ap-modal')?.querySelector(':scope > div');
    if (modalBody) modalBody.scrollTop = focusState.modalScrollTop;
  };
  restoreFocus();
  if (result && typeof result.then === 'function') result.then(restoreFocus, restoreFocus);
};

document.addEventListener('input', e => {
  const immediateElement = e.target.closest('[data-input-action]');
  if (immediateElement) handle(immediateElement.dataset.inputAction, immediateElement);
  const el = e.target.closest('[data-debounce-action]');
  if (!el) return;
  clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => handleDebouncedInput(el), 300);
});

document.addEventListener('focusin', e => {
  const el = e.target.closest('[data-focus-action]');
  if (el) handle(el.dataset.focusAction, el);
});

let draftTestResizeActive = false;
const updateDraftTestDrawerWidth = clientX => {
  const maxWidth = Math.max(480, Math.min(1100, window.innerWidth - 32));
  const width = Math.min(maxWidth, Math.max(480, Math.round(window.innerWidth - clientX)));
  state.draftTestDrawerWidth = width;
  document.querySelector('.ap-draft-test-drawer')?.style.setProperty('--ap-draft-drawer-width', `${width}px`);
};
const finishDraftTestResize = () => {
  if (!draftTestResizeActive) return;
  draftTestResizeActive = false;
  document.body.classList.remove('is-draft-test-resizing');
  localStorage.setItem('studio-draft-test-drawer-width', String(state.draftTestDrawerWidth));
};

document.addEventListener('pointerdown', e => {
  if (!e.target.closest('[data-draft-test-resize]')) return;
  e.preventDefault();
  draftTestResizeActive = true;
  document.body.classList.add('is-draft-test-resizing');
  updateDraftTestDrawerWidth(e.clientX);
});
document.addEventListener('pointermove', e => {
  if (!draftTestResizeActive) return;
  e.preventDefault();
  updateDraftTestDrawerWidth(e.clientX);
});
document.addEventListener('pointerup', finishDraftTestResize);
window.addEventListener('blur', finishDraftTestResize);

document.addEventListener('keydown', e => {
  const debugInput = e.target.closest('[data-debug-input-history="true"]');
  if (debugInput) {
    handleDebugInputKeydown(e, debugInput);
    if (e.defaultPrevented) return;
  }
  const composer = e.target.closest('textarea[data-composer-send-action]');
  if (composer && isComposerSendShortcut(e)) {
    e.preventDefault();
    handle(composer.dataset.composerSendAction, composer);
    return;
  }
  const el = e.target.closest('[data-debounce-action][data-preserve-focus="true"]');
  if (!el || e.key !== 'Enter') return;
  // Enter 只用于立即应用筛选，不能提交或关闭当前弹窗。
  e.preventDefault();
  clearTimeout(_debounceTimer);
  handleDebouncedInput(el);
});

document.addEventListener('change', e => {
  const el = e.target.closest('[data-change-action]');
  if (el) handle(el.dataset.changeAction, el);
});

// scroll 不冒泡，使用捕获监听调试时间线；用户离开底部后暂停流式自动跟随。
document.addEventListener('scroll', e => {
  if (e.target?.id === 'debug-messages-container') updateDebugAutoFollow(e.target);
  if (e.target?.classList?.contains('ap-chat-messages')) updateChatAutoFollow(e.target);
}, true);

setInterval(() => {
  document.querySelectorAll('[data-runtime-elapsed]').forEach(element => {
    element.textContent = formatRuntimeElapsed(Date.now() - Number(element.dataset.runtimeStartedAt || Date.now()));
  });
}, 1000);

// 浏览器前进/后退
const restoreLocation = () => {
  applyLocation();
  if (state.view === 'chat') state.chatAutoFollow = true;
  const scopedLoading = state.view === 'resources' ? loadResourcePage(state.workspace)
    : state.view === 'evolution' ? loadEvolutionWorkspace()
    : state.view === 'quality' ? loadQualityOverview()
    : state.view === 'agent-detail' ? loadAgentMemory()
      : null;
  render();
  if (scopedLoading) Promise.resolve(scopedLoading).finally(() => render());
  if (state.view === 'chat') {
    loadPublishedChat().then(() => render()).catch(error => {
      state.chatLoadError = error?.message || '会话加载失败';
      render();
    });
  }
  if (state.view === 'spaces') {
    const s = workspace();
    if (s) loadWorkspaceMembers(s.code).then(() => render()).catch(() => {});
  }
  if (state.view === 'credentials') {
    loadCredentialsAndRender();
  }
  if (state.view === 'run-detail' && state.selectedRun && workspace()) {
    loadRuntimeRunDetail(state.selectedRun).then(() => render()).catch(() => render());
  }
};

window.addEventListener('popstate', restoreLocation);

// 暴露调试接口（开发时可在控制台访问）
window.__agentPlatformPrototype = { state, go, handle, render };

// 加载静态数据（skills/subAgents/tools）和后端空间列表，完成后渲染
loadStaticData();
loadWorkspaces().finally(() => {
  applyLocation();
  render();
  const s = workspace();
  if (s) {
    const resourceLoading = state.view === 'resources'
      ? loadResourcePage(s.code)
      : loadResourceCatalog(s.code);
    resourceLoading.then(() => {
      applyLocation();
      if (state.view === 'chat') return loadPublishedChat();
      if (state.view === 'evolution') return loadEvolutionWorkspace();
      if (state.view === 'quality') return loadQualityOverview();
      if (state.view === 'agent-detail') return loadAgentMemory();
      return undefined;
    }).catch(error => {
      if (state.view === 'chat') state.chatLoadError = error?.message || 'Agent 加载失败';
    }).finally(() => render());
    loadRuntimeRuns().then(() => render());
    if (state.view === 'run-detail' && state.selectedRun) {
      loadRuntimeRunDetail(state.selectedRun).then(() => render()).catch(() => render());
    }
  }
  // 初始落点就是 spaces 页时也要加载成员
  if (state.view === 'spaces') {
    const s = workspace();
    if (s) loadWorkspaceMembers(s.code).then(() => render()).catch(() => {});
  }
  if (state.view === 'credentials') {
    loadCredentialsAndRender();
  }
});
