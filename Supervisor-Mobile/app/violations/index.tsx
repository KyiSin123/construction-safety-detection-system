import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { api, Violation } from '../../src/api';
import { useAuth } from '../../src/auth';

const STATUSES = ['pending', 'worker_submitted', 'resolved'] as const;
type Status = typeof STATUSES[number];
const label = (value: Status) => value === 'worker_submitted' ? 'Submissions' : value;

export default function Violations() {
  const { token, supervisor } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<Status>('pending');
  const [items, setItems] = useState<Violation[]>([]);
  const [counts, setCounts] = useState({ pending:0, worker_submitted:0, resolved:0 });
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const knownPending = useRef(new Set<string>());
  const loadedPending = useRef(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [next, unread, nextCounts] = await Promise.all([
        api.violations(token, status), api.unreadCount(token), api.violationCounts(token),
      ]);
      if (status === 'pending') {
        const additions = next.filter(item => !knownPending.current.has(item.instance_id));
        if (loadedPending.current && additions.length) {
          const first = additions[0], unknown = first.alert_priority === 1;
          Alert.alert(
            unknown ? 'URGENT: No ID person' : 'New PPE safety alert',
            unknown ? 'Unknown person on site. Check this person immediately.' : `${first.worker_name || first.worker_number}: missing ${first.missing_ppe.join(', ') || 'required PPE'}`,
          );
        }
        knownPending.current = new Set(next.map(item => item.instance_id));
        loadedPending.current = true;
      }
      setItems(next); setUnreadCount(unread.unread_count); setCounts(nextCounts); setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Unable to load alerts');
    } finally { setLoading(false); }
  }, [token, status]);

  useEffect(() => {
    setLoading(true); void load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [load]);

  const open = async (item: Violation) => {
    if (token && !item.is_read) {
      try {
        await api.markRead(token, item.instance_id);
        setUnreadCount(value => Math.max(0, value - 1));
      } catch {}
    }
    router.push(`/violations/${item.instance_id}`);
  };
  const markAllRead = async () => {
    if (!token || !unreadCount) return;
    try { await api.markRead(token); setItems(value => value.map(item => ({...item,is_read:true}))); setUnreadCount(0); }
    catch (value) { Alert.alert('Unable to mark alerts read', value instanceof Error ? value.message : 'Please try again.'); }
  };

  return <View style={styles.page}>
    <View style={styles.header}>
      <View><Text style={styles.title}>Assigned alerts</Text><Text style={styles.subtitle}>No-ID alerts require an immediate site check.</Text></View>
      <View style={styles.actions}>
        <Pressable accessibilityLabel={`${unreadCount} unread notifications`} onPress={markAllRead} style={styles.bell}>
          <Text style={styles.bellText}>!</Text>{unreadCount > 0 && <Text style={styles.badge}>{unreadCount > 99 ? '99+' : unreadCount}</Text>}
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Open profile" style={styles.profileButton} onPress={() => router.push('/profile')}>
          <Text style={styles.profileIcon}>{supervisor?.display_name?.trim().charAt(0).toUpperCase() || 'P'}</Text>
        </Pressable>
      </View>
    </View>
    {unreadCount > 0 && <Pressable onPress={markAllRead}><Text style={styles.markAll}>Mark all notifications read</Text></Pressable>}
    <View style={styles.tabs}>{STATUSES.map(value => <Pressable key={value} onPress={() => setStatus(value)} style={[styles.tab,status===value&&styles.tabActive]}><Text style={[styles.tabText,status===value&&styles.tabTextActive]}>{label(value)} ({counts[value]})</Text></Pressable>)}</View>
    <ScrollView contentContainerStyle={styles.list} refreshControl={<RefreshControl refreshing={loading} onRefresh={load}/>}>
      {loading && !items.length && <ActivityIndicator/>}{!!error&&<Text style={styles.error}>{error}</Text>}
      {!loading&&!items.length&&<Text style={styles.empty}>No {label(status).toLowerCase()} assigned to you.</Text>}
      {items.map(item => <Pressable key={item.instance_id} onPress={() => open(item)} style={[styles.card,item.alert_priority===1&&styles.urgent,!item.is_read&&styles.unread]}>
        <View style={styles.cardTop}><Text style={styles.worker}>{item.alert_priority===1?'NO ID — CHECK IMMEDIATELY':item.worker_name||item.worker_number}</Text><Text style={[styles.priority,item.alert_priority===1&&styles.priorityUrgent]}>P{item.alert_priority}</Text></View>
        <Text style={styles.meta}>{item.worker_number||item.identity_status}{item.worker_team?` | ${item.worker_team}`:''}</Text>
        {item.review_status==='worker_submitted'&&<Text style={styles.review}>Resolved by worker — review required</Text>}
        <Text style={styles.ppe}>Missing: {item.missing_ppe.join(', ')||'Required PPE'}</Text>
        <Text style={styles.meta}>Detected {item.first_detected} | {item.snapshot_count} snapshots</Text>
        {item.review_status==='worker_submitted'&&item.worker_proof_at&&<Text style={styles.meta}>Proof submitted {item.worker_proof_at}</Text>}
      </Pressable>)}
    </ScrollView>
  </View>;
}

const styles=StyleSheet.create({
  page:{flex:1,padding:16},header:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',marginBottom:8},
  title:{fontSize:23,fontWeight:'800',color:'#172033'},subtitle:{color:'#637083',marginTop:3,maxWidth:230},actions:{flexDirection:'row',alignItems:'center',gap:14},
  bell:{position:'relative',width:34,height:34,borderRadius:17,backgroundColor:'#e9eef5',alignItems:'center',justifyContent:'center'},bellText:{fontSize:20,fontWeight:'900',color:'#43516a'},
  badge:{position:'absolute',right:-9,top:-7,minWidth:18,height:18,borderRadius:9,paddingHorizontal:4,textAlign:'center',color:'#fff',backgroundColor:'#b42318',fontSize:11,fontWeight:'800',overflow:'hidden'},
  profileButton:{width:42,height:42,borderRadius:21,backgroundColor:'#1769d1',alignItems:'center',justifyContent:'center'},profileIcon:{color:'#fff',fontSize:18,fontWeight:'800'},
  markAll:{alignSelf:'flex-end',color:'#1769d1',fontWeight:'700',fontSize:12,marginBottom:10},tabs:{flexDirection:'row',gap:8,marginBottom:14},
  tab:{flex:1,alignItems:'center',paddingVertical:9,borderRadius:5,backgroundColor:'#e9eef5'},tabActive:{backgroundColor:'#1769d1'},tabText:{color:'#43516a',fontSize:12,textTransform:'capitalize'},tabTextActive:{color:'#fff',fontWeight:'700'},
  list:{gap:10,paddingBottom:24},card:{backgroundColor:'#fff',borderRadius:8,padding:16,borderWidth:1,borderColor:'#dbe1ea'},unread:{borderColor:'#1769d1',borderWidth:2},urgent:{borderColor:'#b42318',backgroundColor:'#fff5f4'},
  cardTop:{flexDirection:'row',justifyContent:'space-between',gap:10},worker:{fontSize:17,fontWeight:'700',color:'#172033',flexShrink:1},priority:{paddingHorizontal:8,paddingVertical:3,borderRadius:12,fontSize:12,fontWeight:'800',overflow:'hidden',backgroundColor:'#fff0d7',color:'#8a5600'},priorityUrgent:{backgroundColor:'#b42318',color:'#fff'},
  meta:{color:'#637083',marginTop:7,fontSize:12},review:{color:'#b54708',fontWeight:'800',marginTop:9},ppe:{color:'#b42318',fontWeight:'700',marginTop:10},
  error:{color:'#b42318',backgroundColor:'#fff',padding:14,borderRadius:6},empty:{textAlign:'center',color:'#637083',marginTop:42},
});
