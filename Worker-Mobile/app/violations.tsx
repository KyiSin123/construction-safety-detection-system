import { useCallback, useState } from 'react';
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView,
  StyleSheet, Text, View,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { api, Violation } from '../src/api';
import { useAuth } from '../src/auth';
import { AuthenticatedImage } from '../src/AuthenticatedImage';

const STATUSES = ['pending', 'worker_submitted', 'resolved'] as const;
type Status = typeof STATUSES[number];
type Counts = Record<Status, number>;

const label = (status: Status) => status === 'worker_submitted' ? 'Submitted' : (
  status.charAt(0).toUpperCase() + status.slice(1)
);

export default function Violations() {
  const { token, worker } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<Violation[]>([]);
  const [status, setStatus] = useState<Status>('pending');
  const [counts, setCounts] = useState<Counts>({ pending: 0, worker_submitted: 0, resolved: 0 });
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (nextPage = 1) => {
    if (!token) return;
    setLoading(true);
    try {
      const [violations, nextCounts] = await Promise.all([
        api.violations(token, nextPage, status),
        api.violationCounts(token),
      ]);
      setItems(current => nextPage === 1 ? violations.items : [...current, ...violations.items]);
      setPage(nextPage);
      setMore(violations.has_more);
      setCounts(nextCounts);
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Unable to load safety records');
    } finally {
      setLoading(false);
    }
  }, [token, status]);

  useFocusEffect(useCallback(() => {
    void load(1);
  }, [load]));

  const changeStatus = (next: Status) => {
    setItems([]);
    setPage(1);
    setStatus(next);
  };

  return <View style={styles.page}>
    <View style={styles.header}>
      <View>
        <Text style={styles.title}>Hello, {worker?.name}</Text>
        <Text style={styles.subtitle}>My safety records</Text>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Open profile"
        style={styles.profileButton}
        onPress={() => router.push('/profile')}
      >
        <Text style={styles.profileIcon}>{worker?.name?.trim().charAt(0).toUpperCase() || 'P'}</Text>
      </Pressable>
    </View>

    <View style={styles.tabs}>
      {STATUSES.map(value => <Pressable
        key={value}
        onPress={() => changeStatus(value)}
        style={[styles.tab, status === value && styles.activeTab]}
      >
        <Text style={[styles.tabText, status === value && styles.activeTabText]}>
          {label(value)} ({counts[value]})
        </Text>
      </Pressable>)}
    </View>

    <ScrollView
      refreshControl={<RefreshControl refreshing={loading && page === 1} onRefresh={() => load(1)} />}
      contentContainerStyle={styles.list}
    >
      {!!error && <Text style={styles.error}>{error}</Text>}
      {loading && page === 1 && !items.length ? <ActivityIndicator /> : null}
      {!loading && !items.length ? <Text style={styles.empty}>No {label(status).toLowerCase()} safety records.</Text> : null}
      {items.map(item => <View key={item.instance_id} style={styles.card}>
        {item.snapshot_url && token ? <AuthenticatedImage path={item.snapshot_url} token={token} style={styles.snapshot} /> : null}
        <Text style={styles.heading}>Missing: {item.missing_ppe.join(', ') || 'PPE'}</Text>
        <Text style={styles.meta}>Detected {item.first_detected}</Text>
        {item.review_status === 'pending' && <Text style={styles.pending}>Action required</Text>}
        {item.review_status === 'worker_submitted' && <Text style={styles.submitted}>Awaiting supervisor approval</Text>}
        {item.review_status === 'resolved' && <Text style={styles.resolved}>Resolved</Text>}
        {item.review_reason ? <Text style={styles.note}>Supervisor review: {item.review_reason}</Text> : null}
        {item.reviewed_by ? <Text style={styles.meta}>Reviewed by {item.reviewed_by}</Text> : null}
        {item.review_status === 'pending' ? <Pressable
          style={styles.proofButton}
          onPress={() => router.push(`/proof/${item.instance_id}`)}
        >
          <Text style={styles.buttonText}>Acknowledge and submit proof</Text>
        </Pressable> : null}
      </View>)}
      {more ? <Pressable style={styles.more} onPress={() => load(page + 1)} disabled={loading}>
        <Text style={styles.link}>{loading ? 'Loading...' : 'Load more'}</Text>
      </Pressable> : null}
    </ScrollView>
  </View>;
}

const styles = StyleSheet.create({
  page:{flex:1,padding:16},
  header:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',marginBottom:16},
  title:{fontSize:22,fontWeight:'800',color:'#172033'},
  subtitle:{color:'#637083',marginTop:3},
  profileButton:{width:42,height:42,borderRadius:21,backgroundColor:'#1769d1',alignItems:'center',justifyContent:'center'},
  profileIcon:{color:'#fff',fontSize:18,fontWeight:'800'},
  tabs:{flexDirection:'row',gap:7,marginBottom:14},
  tab:{flex:1,alignItems:'center',paddingVertical:10,paddingHorizontal:3,borderRadius:6,backgroundColor:'#e9eef5'},
  activeTab:{backgroundColor:'#1769d1'},
  tabText:{color:'#43516a',fontWeight:'700',fontSize:12},
  activeTabText:{color:'#fff'},
  list:{gap:12,paddingBottom:24},
  card:{backgroundColor:'#fff',padding:16,borderRadius:8,borderWidth:1,borderColor:'#dbe1ea'},
  snapshot:{width:'100%',height:220,borderRadius:6,backgroundColor:'#dbe1ea',marginBottom:12},
  heading:{fontSize:17,fontWeight:'700'},
  meta:{color:'#637083',marginTop:5,fontSize:12},
  pending:{color:'#b42318',fontWeight:'800',marginTop:9},
  submitted:{color:'#b54708',fontWeight:'800',marginTop:9},
  resolved:{color:'#067647',fontWeight:'800',marginTop:9},
  note:{marginTop:8},
  proofButton:{backgroundColor:'#1769d1',padding:12,borderRadius:5,alignItems:'center',marginTop:14},
  buttonText:{color:'#fff',fontWeight:'700'},
  error:{color:'#b42318'},
  empty:{textAlign:'center',color:'#637083',marginTop:40},
  more:{alignItems:'center',padding:14},
  link:{color:'#1769d1',fontWeight:'700'},
});
