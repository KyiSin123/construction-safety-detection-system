export const API_BASE_URL = (process.env.EXPO_PUBLIC_API_BASE_URL || '').replace(/\/$/, '');

export type Supervisor = { id: number; username: string; display_name: string; role: 'admin' | 'supervisor' };
export type Violation = {
  instance_id: string; first_detected: string; last_updated: string; missing_ppe: string[];
  detected_ppe: string[]; worker_number?: string; worker_name?: string; worker_team?: string;
  identity_status: string; review_status: 'pending' | 'worker_submitted' | 'resolved'; review_reason?: string;
  reviewed_by?: string; review_updated_at?: string; delivery_status: string; notified_at?: string;
  snapshot_count: number; alert_priority: 1 | 2 | 3; is_read: boolean; read_at?: string; worker_proof_at?: string;
};
export type ViolationDetail = Violation & {
  snapshots: { id: number; timestamp: string; url: string }[];
  worker_proof_url?: string;
  worker_comment?: string;
  worker_proof_at?: string;
  assignment?: { supervisor_id: number; supervisor_name: string; assigned_at: string };
  worker_delivery?: { status: string; error?: string; notified_at?: string };
  review_events: { previous_status?: string; review_status: string; review_reason?: string; reviewed_by?: string; created_at: string }[];
};
export type WorkerOption = { worker_number: string; name: string; team?: string };

async function request<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  if (!API_BASE_URL) throw new Error('EXPO_PUBLIC_API_BASE_URL is not configured');
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || 'Request failed');
  return data as T;
}

export const api = {
  login: (username: string, password: string) => request<{ access_token: string; supervisor: Supervisor }>('/api/mobile/auth/login', undefined, { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: (token: string) => request<Supervisor>('/api/mobile/me', token),
  violations: (token: string, status: string) => request<Violation[]>(`/api/mobile/violations?status=${encodeURIComponent(status)}`, token),
  violationCounts: (token: string) => request<{ pending: number; worker_submitted: number; resolved: number }>('/api/mobile/violations/counts', token),
  unreadCount: (token: string) => request<{ unread_count: number }>('/api/mobile/notifications/unread-count', token),
  markRead: (token: string, instance_id?: string) => request<{ updated: number }>('/api/mobile/notifications/read', token, { method: 'POST', body: JSON.stringify(instance_id ? { instance_id } : {}) }),
  violation: (token: string, id: string) => request<ViolationDetail>(`/api/mobile/violations/${encodeURIComponent(id)}`, token),
  workers: (token: string, search: string) => request<WorkerOption[]>(`/api/mobile/workers?search=${encodeURIComponent(search)}`, token),
  assignWorker: (token: string, id: string, worker_number: string) => request<{
    message: string;
    assignment: { worker_number: string; worker_name: string; worker_team?: string };
    delivery: { status: string; sent_devices: number; error?: string };
  }>(`/api/mobile/violations/${encodeURIComponent(id)}/assign-worker`, token, { method: 'POST', body: JSON.stringify({ worker_number }) }),
  review: (token: string, id: string, review_status: string, review_reason: string) => request<{ message: string }>(`/api/mobile/violations/${encodeURIComponent(id)}/review`, token, { method: 'PATCH', body: JSON.stringify({ review_status, review_reason }) }),
  device: (token: string, expo_push_token: string, platform: string) => request<{ message: string }>('/api/mobile/devices', token, { method: 'POST', body: JSON.stringify({ expo_push_token, platform }) }),
  unregisterDevice: (token: string) => request('/api/mobile/devices', token, { method: 'DELETE' }),
  testNotification: (token: string) => request<{ message: string; errors?: string[] }>('/api/mobile/notifications/test', token, { method: 'POST' }),
};
