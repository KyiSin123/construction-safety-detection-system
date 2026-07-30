import { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';
import { api, AttendanceRequest } from '../src/api';
import { useAuth } from '../src/auth';

const statuses = ['pending', 'approved', 'rejected'];

export default function AttendanceRequests() {
  const { token } = useAuth(); const router = useRouter();
  const [status, setStatus] = useState('pending'); const [items, setItems] = useState<AttendanceRequest[]>([]);
  const [loading, setLoading] = useState(false); const [reasons, setReasons] = useState<Record<number, string>>({});
  const load = useCallback(async () => {
    if (!token) return; setLoading(true);
    try { setItems(await api.attendanceRequests(token, status)); }
    catch (error) { Alert.alert('Unable to load', error instanceof Error ? error.message : 'Request failed'); }
    finally { setLoading(false); }
  }, [token, status]);
  useEffect(() => { load(); }, [load]);
  const decide = async (item: AttendanceRequest, decision: 'approved' | 'rejected') => {
    if (!token) return; const reason = (reasons[item.id] || '').trim();
    if (decision === 'rejected' && !reason) { Alert.alert('Reason required', 'Explain why the request is rejected.'); return; }
    try { const result = await api.decideAttendance(token, item.id, decision, reason); Alert.alert('Attendance', result.message); load(); }
    catch (error) { Alert.alert('Unable to decide', error instanceof Error ? error.message : 'Request failed'); }
  };
  return <View style={styles.page}><View style={styles.tabs}>{statuses.map(value =>
    <Pressable key={value} style={[styles.tab, status === value && styles.active]} onPress={() => setStatus(value)}><Text style={status === value ? styles.white : styles.tabText}>{value}</Text></Pressable>
  )}</View><ScrollView contentContainerStyle={styles.list} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
    <Pressable onPress={() => router.replace('/violations')}><Text style={styles.link}>Back to safety alerts</Text></Pressable>
    {!items.length && !loading ? <Text style={styles.empty}>No {status} attendance requests.</Text> : null}
    {items.map(item => <View key={item.id} style={styles.card}><Text style={styles.name}>{item.worker_name}</Text>
      <Text style={styles.meta}>{item.worker_number}{item.worker_team ? ` · ${item.worker_team}` : ''}</Text>
      <Text style={styles.action}>{item.action.replace('_', ' ')} · {item.requested_at}</Text><Text style={styles.reason}>{item.reason}</Text>
      {item.status === 'pending' ? <><TextInput style={styles.input} value={reasons[item.id] || ''} onChangeText={value => setReasons(current => ({ ...current, [item.id]: value }))} placeholder="Rejection reason (required only to reject)" />
        <View style={styles.buttons}><Pressable style={[styles.button, styles.approve]} onPress={() => decide(item, 'approved')}><Text style={styles.white}>Approve exact time</Text></Pressable>
          <Pressable style={[styles.button, styles.reject]} onPress={() => decide(item, 'rejected')}><Text style={styles.white}>Reject</Text></Pressable></View></>
        : <Text style={styles.meta}>Decided by {item.reviewer_name || 'supervisor'}{item.decision_reason ? `: ${item.decision_reason}` : ''}</Text>}
    </View>)}
  </ScrollView></View>;
}

const styles=StyleSheet.create({page:{flex:1,padding:16},tabs:{flexDirection:'row',gap:7,marginBottom:12},tab:{flex:1,alignItems:'center',padding:10,borderRadius:6,backgroundColor:'#e9eef5'},active:{backgroundColor:'#1769d1'},tabText:{textTransform:'capitalize'},white:{color:'#fff',fontWeight:'700',textTransform:'capitalize'},list:{gap:10,paddingBottom:25},link:{color:'#1769d1',fontWeight:'700',marginBottom:4},card:{backgroundColor:'#fff',padding:16,borderRadius:8,borderWidth:1,borderColor:'#dbe1ea'},name:{fontSize:18,fontWeight:'700'},meta:{color:'#637083',marginTop:5},action:{color:'#1769d1',fontWeight:'700',marginTop:10,textTransform:'capitalize'},reason:{marginTop:8},input:{borderWidth:1,borderColor:'#dbe1ea',padding:11,borderRadius:6,marginTop:12},buttons:{flexDirection:'row',gap:8,marginTop:10},button:{flex:1,padding:12,borderRadius:6,alignItems:'center'},approve:{backgroundColor:'#11743a'},reject:{backgroundColor:'#b42318'},empty:{color:'#637083',textAlign:'center',marginTop:40}});
