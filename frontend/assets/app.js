const API_BASE = window.SMARTQA_API_BASE || `${window.location.origin}/api`;
const AUTH_TOKEN_KEY = 'smartqa_access_token';
const AUTH_USER_KEY = 'smartqa_user';

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || '';
}

function setAuthSession(token, user) {
  if (token) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
  }
  if (user) {
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  }
}

function clearAuthSession() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
}

async function apiFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 && !location.pathname.endsWith('/login.html')) {
    location.href = `login.html?next=${encodeURIComponent(location.pathname.split('/').pop() || 'chat.html')}`;
  }
  return res;
}

async function fetchAuthSession() {
  const res = await apiFetch(`${API_BASE}/auth/session`);
  return res.json();
}

async function ensureAuthenticated() {
  const session = await fetchAuthSession();
  if (session.required && !session.authenticated) {
    location.href = `login.html?next=${encodeURIComponent(location.pathname.split('/').pop() || 'chat.html')}`;
    return false;
  }
  return true;
}

async function loginWithSupabase(email, password) {
  const health = await fetchSystemHealth();
  if (!health.supabase || !health.supabase.enabled) {
    return { error: 'Supabase 未启用，无法登录' };
  }
  const supabaseUrl = health.supabase_public && health.supabase_public.url;
  const anonKey = health.supabase_public && health.supabase_public.anon_key;
  if (!supabaseUrl || !anonKey) {
    return { error: 'Supabase 登录配置不完整' };
  }
  const res = await fetch(`${supabaseUrl}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: anonKey,
    },
    body: JSON.stringify({ email, password })
  });
  const body = await res.json();
  if (!res.ok) {
    return { error: body.error_description || body.msg || body.error || '登录失败' };
  }
  setAuthSession(body.access_token, body.user);
  return body;
}

async function fetchConversations() {
  const res = await apiFetch(`${API_BASE}/conversations`);
  return res.json();
}

async function fetchConversation(id) {
  const res = await apiFetch(`${API_BASE}/conversations/${id}`);
  return res.json();
}

async function sendChatMessage(sessionId, message) {
  const res = await apiFetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message })
  });
  return res.json();
}

async function updateConversationStatus(id, status, reason = '') {
  const res = await apiFetch(`${API_BASE}/conversations/${id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, reason })
  });
  return res.json();
}

async function updateConversationOperations(id, updates) {
  const res = await apiFetch(`${API_BASE}/conversations/${id}/operations`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  });
  return res.json();
}

async function transcribeNonText(file, kind) {
  const form = new FormData();
  form.append('file', file);
  if (kind) form.append('kind', kind);
  const res = await apiFetch(`${API_BASE}/non-text/transcribe`, {
    method: 'POST',
    body: form
  });
  return res.json();
}

async function sendHumanReply(id, content, resolve = true) {
  const res = await apiFetch(`${API_BASE}/conversations/${id}/human-reply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, resolve })
  });
  return res.json();
}

async function fetchSystemHealth() {
  const res = await apiFetch(`${API_BASE}/system/health`);
  return res.json();
}

async function fetchWeComStatus() {
  const res = await apiFetch(`${API_BASE}/wecom/status`);
  return res.json();
}

async function simulateWeComMessage(payload) {
  const res = await apiFetch(`${API_BASE}/wecom/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {})
  });
  return res.json();
}

async function syncWeComCustomerService(payload) {
  const res = await apiFetch(`${API_BASE}/wecom-kf/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {})
  });
  return res.json();
}

async function fetchDashboard() {
  const res = await apiFetch(`${API_BASE}/dashboard`);
  return res.json();
}

async function fetchOperationsMonitor() {
  const res = await apiFetch(`${API_BASE}/operations/monitor`);
  return res.json();
}

async function sendOperationsAlerts() {
  const res = await apiFetch(`${API_BASE}/operations/send-alerts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return res.json();
}

async function resolveCurrentOperations(note) {
  const res = await apiFetch(`${API_BASE}/operations/resolve-current`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note: note || '' })
  });
  return res.json();
}

async function fetchAuditLogs(filters = {}) {
  const params = new URLSearchParams();
  if (filters.limit) params.set('limit', filters.limit);
  if (filters.target_type) params.set('target_type', filters.target_type);
  if (filters.action) params.set('action', filters.action);
  const query = params.toString();
  const res = await apiFetch(`${API_BASE}/audit-logs${query ? '?' + query : ''}`);
  return res.json();
}

async function fetchKnowledgeGaps() {
  const res = await apiFetch(`${API_BASE}/knowledge-gaps`);
  return res.json();
}

async function updateKnowledgeGap(id, updates) {
  const res = await apiFetch(`${API_BASE}/knowledge-gaps/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  });
  return res.json();
}

async function promoteKnowledgeGap(id, payload) {
  const res = await apiFetch(`${API_BASE}/knowledge-gaps/${id}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  return res.json();
}

async function fetchKnowledge(category, itemType) {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (itemType) params.set('item_type', itemType);
  const query = params.toString();
  const url = `${API_BASE}/knowledge${query ? '?' + query : ''}`;
  const res = await apiFetch(url);
  return res.json();
}

async function addKnowledge(item) {
  const res = await apiFetch(`${API_BASE}/knowledge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(item)
  });
  return res.json();
}

async function updateKnowledge(id, updates) {
  const res = await apiFetch(`${API_BASE}/knowledge/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  });
  return res.json();
}

async function syncKnowledge(id) {
  const res = await apiFetch(`${API_BASE}/knowledge/${id}/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return res.json();
}

async function syncFailedKnowledge() {
  const res = await apiFetch(`${API_BASE}/knowledge/sync-failed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return res.json();
}

async function syncPendingKnowledge() {
  const res = await apiFetch(`${API_BASE}/knowledge/sync-pending`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return res.json();
}

async function fetchKnowledgeSyncJobs(itemId) {
  const url = itemId ? `${API_BASE}/knowledge-sync-jobs?item_id=${encodeURIComponent(itemId)}` : `${API_BASE}/knowledge-sync-jobs`;
  const res = await apiFetch(url);
  return res.json();
}

async function fetchDifyDocumentStatus() {
  const res = await apiFetch(`${API_BASE}/knowledge/dify-documents/status`);
  return res.json();
}

async function cleanupStaleDifyDocuments(limit = 20) {
  const res = await apiFetch(`${API_BASE}/knowledge/dify-documents/cleanup-stale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit })
  });
  return res.json();
}

async function fetchKnowledgeVersions(itemId) {
  const res = await apiFetch(`${API_BASE}/knowledge/${itemId}/versions`);
  return res.json();
}

async function fetchKnowledgeQuality() {
  const res = await apiFetch(`${API_BASE}/knowledge-quality`);
  return res.json();
}

async function fetchDataGovernance() {
  const res = await apiFetch(`${API_BASE}/data-governance`);
  return res.json();
}
