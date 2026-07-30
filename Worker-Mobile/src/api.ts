export const API_BASE_URL=(process.env.EXPO_PUBLIC_API_BASE_URL||'').replace(/\/$/,'');
export type Worker={worker_number:string;name:string;team?:string;phone?:string;email?:string;has_profile_photo:boolean};
export type Page<T>={items:T[];page:number;per_page:number;total:number;has_more:boolean};
export type Violation={instance_id:string;first_detected:string;missing_ppe:string[];review_status:'pending'|'worker_submitted'|'resolved'|'ignored';worker_comment?:string;has_proof:boolean;review_reason?:string;reviewed_by?:string;review_updated_at?:string};
export type Attendance={id:number;attendance_date:string;check_in_at:string;check_out_at?:string;recorded_by?:string;check_in_reason?:string;check_out_reason?:string;status:'completed'|'on_site'};
export type AttendanceRequest={id:number;action:'check_in'|'check_out';requested_at:string;reason:string;status:'pending'|'approved'|'rejected';reviewer_name?:string;decision_reason?:string;decided_at?:string;created_at:string};
async function request<T>(path:string,token?:string,options:RequestInit={}):Promise<T>{if(!API_BASE_URL)throw new Error('EXPO_PUBLIC_API_BASE_URL is not configured');const r=await fetch(`${API_BASE_URL}${path}`,{...options,headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:`Bearer ${token}`} : {}),...options.headers}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||d.message||'Request failed');return d as T}
export const api={
  login:(worker_number:string,password:string)=>request<{access_token:string;worker:Worker}>('/api/worker/auth/login',undefined,{method:'POST',body:JSON.stringify({worker_number,password})}),
  me:(token:string)=>request<Worker>('/api/worker/me',token),
  updateProfile:(token:string,payload:{phone:string;email:string;image_base64?:string})=>request<{message:string;worker:Worker}>('/api/worker/me',token,{method:'PATCH',body:JSON.stringify(payload)}),
  changePassword:(token:string,current_password:string,new_password:string)=>request<{message:string}>('/api/worker/password',token,{method:'PATCH',body:JSON.stringify({current_password,new_password})}),
  violations:(token:string,page=1,status='')=>request<Page<Violation>>(`/api/worker/violations?page=${page}&status=${encodeURIComponent(status)}`,token),
  device:(token:string,expo_push_token:string,platform:string)=>request<{message:string}>('/api/worker/devices',token,{method:'POST',body:JSON.stringify({expo_push_token,platform})}),
  unregisterDevice:(token:string)=>request('/api/worker/devices',token,{method:'DELETE'}),
  attendance:(token:string,page=1,month='')=>request<Page<Attendance>>(`/api/worker/attendance?page=${page}&month=${encodeURIComponent(month)}`,token),
  attendanceRequests:(token:string)=>request<AttendanceRequest[]>('/api/worker/attendance-requests',token),
  submitAttendanceRequest:(token:string,payload:{action:string;requested_at:string;reason:string})=>request<{message:string}>('/api/worker/attendance-requests',token,{method:'POST',body:JSON.stringify(payload)}),
  submitProof:(token:string,id:string,comment:string,image_base64:string)=>request<{message:string}>(`/api/worker/violations/${encodeURIComponent(id)}/proof`,token,{method:'POST',body:JSON.stringify({comment,image_base64})})
};
