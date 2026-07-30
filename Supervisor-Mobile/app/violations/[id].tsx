import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { api, ViolationDetail, WorkerOption } from '../../src/api';
import { useAuth } from '../../src/auth';

export default function ViolationDetails() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [item, setItem] = useState<ViolationDetail | null>(null);
  const [status, setStatus] = useState<'resolved' | 'ignored'>('resolved');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');
  const [workers, setWorkers] = useState<WorkerOption[]>([]);
  const [selectedWorker, setSelectedWorker] = useState<WorkerOption | null>(null);

  const load = async () => {
    if (!token || !id) return;
    try {
      const value = await api.violation(token, id);
      setItem(value);
      setReason(value.review_reason || '');
      setStatus(value.review_status === 'ignored' ? 'ignored' : 'resolved');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Unable to load violation');
    }
  };
  useEffect(() => { load(); }, [id, token]);
  useEffect(() => {
    if (!token || item?.identity_status === 'confirmed') return;
    const timer = setTimeout(() => {
      api.workers(token, search).then(setWorkers).catch(value =>
        setError(value instanceof Error ? value.message : 'Unable to load workers'));
    }, 250);
    return () => clearTimeout(timer);
  }, [token, search, item?.identity_status]);

  const assign = () => {
    if (!token || !id || !selectedWorker) return;
    Alert.alert(
      'Send Warning Alert?',
      `${selectedWorker.name} (${selectedWorker.worker_number}) will be identified as this worker and receive the safety warning. This choice cannot be changed.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Send warning',
          onPress: async () => {
            setSaving(true); setError('');
            try {
              const result = await api.assignWorker(token, id, selectedWorker.worker_number);
              setItem(current => current ? {
                ...current,
                worker_number: result.assignment.worker_number,
                worker_name: result.assignment.worker_name,
                worker_team: result.assignment.worker_team,
                identity_status: 'confirmed',
                worker_delivery: {
                  status: result.delivery.status,
                  error: result.delivery.error,
                },
              } : current);
              setWorkers([]);
              setSearch('');
              setSelectedWorker(null);
              await load();
              Alert.alert(
                'Worker identified',
                result.delivery.status === 'sent'
                  ? `Notification sent to ${result.delivery.sent_devices} device(s).`
                  : `Assignment saved. ${result.delivery.error || 'Push notification was not delivered.'}`,
              );
            } catch (value) {
              setError(value instanceof Error ? value.message : 'Unable to identify worker');
              await load();
            } finally { setSaving(false); }
          },
        },
      ],
    );
  };
  const save = async () => {
    if (!token || !id) return;
    setSaving(true); setError('');
    try { await api.review(token, id, status, reason); await load(); router.replace('/violations'); }
    catch (value) { setError(value instanceof Error ? value.message : 'Unable to save review'); }
    finally { setSaving(false); }
  };

  if (!item) return <View style={styles.center}>{error ? <Text style={styles.error}>{error}</Text> : <ActivityIndicator />}</View>;
  const helmetReasonRequired = status === 'resolved' && item.missing_ppe.includes('helmet');
  const unknown = item.identity_status !== 'confirmed' || !item.worker_number;
  return <ScrollView contentContainerStyle={styles.page}>
    <View style={styles.panel}>
      <Text style={styles.worker}>{item.worker_name || 'Unknown worker'}</Text>
      <Text style={styles.meta}>{item.worker_number || item.identity_status}{item.worker_team ? `  |  ${item.worker_team}` : ''}</Text>
      <Text style={styles.ppe}>Missing: {item.missing_ppe.join(', ') || 'Required PPE'}</Text>
      <Text style={styles.meta}>Detected {item.first_detected}</Text>
      {item.assignment && <Text style={styles.meta}>Identified by {item.assignment.supervisor_name} at {item.assignment.assigned_at}</Text>}
      {item.worker_delivery && <Text style={styles.meta}>Worker notification: {item.worker_delivery.status}{item.worker_delivery.error ? ` — ${item.worker_delivery.error}` : ''}</Text>}
    </View>
    {item.snapshots.map(snapshot => <View key={snapshot.id} style={styles.panel}>
      <Image source={{ uri: snapshot.url, headers: { Authorization: `Bearer ${token}` } }} style={styles.image} resizeMode="cover" />
      <Text style={styles.meta}>Snapshot {snapshot.timestamp}</Text>
    </View>)}
    {unknown && item.review_status === 'pending' && <View style={styles.panel}>
      <Text style={styles.section}>Identify worker</Text>
      <Text style={styles.hint}>Search all active workers. The first confirmed selection is final.</Text>
      <TextInput style={styles.search} value={search} onChangeText={setSearch} placeholder="Search name, worker ID, or team" />
      {workers.map(worker => {
        const selected = selectedWorker?.worker_number === worker.worker_number;
        return <Pressable key={worker.worker_number} style={[styles.workerRow, selected && styles.workerRowSelected]} onPress={() => setSelectedWorker(worker)} disabled={saving}>
        <View><Text style={styles.workerName}>{worker.name}</Text><Text style={styles.meta}>{worker.worker_number}{worker.team ? `  |  ${worker.team}` : ''}</Text></View>
        <Text style={[styles.select, selected && styles.selectedText]}>{selected ? '✓ Selected' : 'Select'}</Text>
      </Pressable>})}
      {!workers.length && <Text style={styles.hint}>No active workers found.</Text>}
      {selectedWorker && <View style={styles.selectionSummary}>
        <Text style={styles.selectionTitle}>Selected worker</Text>
        <Text style={styles.selectionName}>{selectedWorker.name}</Text>
        <Text style={styles.meta}>{selectedWorker.worker_number}{selectedWorker.team ? `  |  ${selectedWorker.team}` : ''}</Text>
        <Text style={styles.hint}>The worker has not been assigned or notified yet.</Text>
      </View>}
      <Pressable style={[styles.warningButton, (!selectedWorker || saving) && styles.dim]} onPress={assign} disabled={!selectedWorker || saving}>
        <Text style={styles.saveText}>{saving ? 'Sending warning...' : 'Send Warning Alert'}</Text>
      </Pressable>
    </View>}
    <View style={styles.panel}>
      <Text style={styles.section}>Close this alert</Text>
      <View style={styles.statuses}>{(['resolved','ignored'] as const).map(value => <Pressable key={value} onPress={() => setStatus(value)} style={[styles.choice,status===value&&styles.choiceActive]}><Text style={status===value?styles.choiceActiveText:styles.choiceText}>{value}</Text></Pressable>)}</View>
      <TextInput style={styles.reason} multiline placeholder={helmetReasonRequired ? 'Helmet reason is required' : 'Reason'} value={reason} onChangeText={setReason} />
      <Text style={styles.hint}>{status === 'ignored' ? 'A reason is required when ignoring a violation.' : helmetReasonRequired ? 'Explain why the worker was not wearing a helmet.' : 'Add a resolution note for the audit history.'}</Text>
      {!!error && <Text style={styles.error}>{error}</Text>}
      <Pressable style={[styles.save,saving&&styles.dim]} onPress={save} disabled={saving}><Text style={styles.saveText}>{saving ? 'Saving...' : `Mark ${status}`}</Text></Pressable>
    </View>
    {item.review_events.length > 0 && <View style={styles.panel}><Text style={styles.section}>Review history</Text>{item.review_events.map((event,index) => <View key={`${event.created_at}-${index}`} style={styles.event}><Text style={styles.eventTitle}>{event.review_status} {event.reviewed_by ? `by ${event.reviewed_by}` : ''}</Text><Text style={styles.meta}>{event.created_at}</Text>{event.review_reason ? <Text>{event.review_reason}</Text> : null}</View>)}</View>}
  </ScrollView>;
}

const styles=StyleSheet.create({page:{padding:16,gap:12},center:{flex:1,justifyContent:'center',alignItems:'center'},panel:{backgroundColor:'#fff',padding:16,borderRadius:8,borderWidth:1,borderColor:'#dbe1ea'},worker:{fontSize:21,fontWeight:'700',color:'#172033'},meta:{color:'#637083',fontSize:13,marginTop:7},ppe:{color:'#b42318',fontWeight:'700',marginTop:12},section:{fontSize:17,fontWeight:'700',marginBottom:12},image:{width:'100%',height:230,borderRadius:5,backgroundColor:'#dbe1ea'},search:{borderWidth:1,borderColor:'#dbe1ea',padding:12,borderRadius:5,marginTop:12},workerRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',borderTopWidth:1,borderColor:'#e3e7ed',paddingVertical:12,paddingHorizontal:8},workerRowSelected:{backgroundColor:'#eaf2ff',borderWidth:2,borderColor:'#1769d1',borderRadius:7,marginTop:6},workerName:{fontWeight:'700'},select:{color:'#1769d1',fontWeight:'700'},selectedText:{color:'#0b57b7'},selectionSummary:{backgroundColor:'#f0f7ff',borderWidth:1,borderColor:'#84adf4',borderRadius:7,padding:12,marginTop:12},selectionTitle:{color:'#1769d1',fontSize:12,fontWeight:'800',textTransform:'uppercase'},selectionName:{fontSize:18,fontWeight:'800',marginTop:4},warningButton:{backgroundColor:'#b42318',alignItems:'center',padding:14,borderRadius:6,marginTop:14},statuses:{flexDirection:'row',gap:8},choice:{flex:1,alignItems:'center',padding:11,borderRadius:5,backgroundColor:'#e9eef5'},choiceActive:{backgroundColor:'#1769d1'},choiceText:{textTransform:'capitalize'},choiceActiveText:{color:'#fff',fontWeight:'700',textTransform:'capitalize'},reason:{minHeight:96,borderWidth:1,borderColor:'#dbe1ea',borderRadius:5,padding:12,textAlignVertical:'top',marginTop:12},hint:{color:'#637083',fontSize:12,marginTop:8},save:{backgroundColor:'#1769d1',alignItems:'center',padding:13,borderRadius:5,marginTop:14},saveText:{color:'#fff',fontWeight:'700',textTransform:'capitalize'},error:{color:'#b42318',marginTop:10},dim:{opacity:.6},event:{borderTopWidth:1,borderColor:'#dbe1ea',paddingTop:10,marginTop:10},eventTitle:{fontWeight:'700',textTransform:'capitalize'}});
