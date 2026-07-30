import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Redirect } from 'expo-router';
import { useAuth } from '../src/auth';
import { api } from '../src/api';

export default function Profile() {
  const { supervisor, token, signOut } = useAuth();
  const [testing, setTesting] = useState(false);
  if (!supervisor) return <Redirect href="/login" />;
  const testPush = async () => {
    if (!token) return;
    setTesting(true);
    try {
      const result = await api.testNotification(token);
      const detail = result.errors?.filter(Boolean).join('\n') ?? '';
      Alert.alert('Push test', detail ? `${result.message}\n\n${detail}` : result.message);
    } catch (value) {
      Alert.alert('Push test failed', value instanceof Error ? value.message : 'Unable to send test notification');
    } finally { setTesting(false); }
  };
  return <ScrollView contentContainerStyle={styles.page}>
    <View style={styles.card}>
      <View style={styles.avatar}><Text style={styles.avatarText}>{supervisor.display_name.trim().charAt(0).toUpperCase()}</Text></View>
      <Text style={styles.name}>{supervisor.display_name}</Text>
      <Text style={styles.detail}>Username: {supervisor.username}</Text>
      <Text style={styles.detail}>Role: {supervisor.role}</Text>
      <Pressable style={styles.testButton} onPress={testPush} disabled={testing}>
        <Text style={styles.buttonText}>{testing ? 'Sending test...' : 'Test push notification'}</Text>
      </Pressable>
    </View>
    <Pressable style={styles.signout} onPress={signOut}><Text style={styles.buttonText}>Sign out</Text></Pressable>
  </ScrollView>;
}

const styles=StyleSheet.create({
  page:{padding:16,gap:12,paddingBottom:30},card:{backgroundColor:'#fff',borderRadius:8,padding:20,borderWidth:1,borderColor:'#dbe1ea'},
  avatar:{width:110,height:110,borderRadius:55,alignSelf:'center',marginBottom:14,backgroundColor:'#1769d1',alignItems:'center',justifyContent:'center'},
  avatarText:{color:'#fff',fontSize:42,fontWeight:'800'},name:{fontSize:22,fontWeight:'700',color:'#172033',textAlign:'center'},
  detail:{marginTop:8,color:'#637083',textAlign:'center'},testButton:{marginTop:24,backgroundColor:'#1769d1',padding:13,borderRadius:6,alignItems:'center'},
  signout:{backgroundColor:'#b42318',padding:13,borderRadius:6,alignItems:'center'},buttonText:{color:'#fff',fontWeight:'700'},
});
