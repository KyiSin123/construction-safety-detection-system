import { useState } from 'react';
import { Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Redirect, Link } from 'expo-router';
import { useAuth } from '../src/auth';

export default function Login() {
  const { token, signIn } = useAuth(); const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  if (token) return <Redirect href="/violations" />;
  const submit = async () => { setBusy(true); setError(''); try { await signIn(username, password); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to sign in'); } finally { setBusy(false); } };
  return <SafeAreaView style={styles.page}><View style={styles.card}><Text style={styles.title}>PPE Supervisor</Text><Text style={styles.subtitle}>Sign in to review assigned safety alerts.</Text><TextInput style={styles.input} placeholder="Username" autoCapitalize="none" value={username} onChangeText={setUsername} /><TextInput style={styles.input} placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} /><Link href="/forgot-password" asChild><Pressable style={styles.forgot}><Text style={styles.forgotText}>Forgot password?</Text></Pressable></Link>{!!error && <Text style={styles.error}>{error}</Text>}<Pressable style={[styles.button, busy && styles.disabled]} onPress={submit} disabled={busy}><Text style={styles.buttonText}>{busy ? 'Signing in...' : 'Sign in'}</Text></Pressable></View></SafeAreaView>;
}
const styles = StyleSheet.create({ page:{flex:1,justifyContent:'center',padding:24,backgroundColor:'#f4f6f9'}, card:{backgroundColor:'#fff',padding:24,borderRadius:8}, title:{fontSize:28,fontWeight:'700',color:'#172033'}, subtitle:{color:'#637083',marginTop:8,marginBottom:22}, input:{borderWidth:1,borderColor:'#dbe1ea',borderRadius:6,padding:13,marginBottom:12,fontSize:16}, forgot:{alignSelf:'flex-end',paddingVertical:4,marginBottom:12}, forgotText:{color:'#1769d1',fontWeight:'600'}, button:{backgroundColor:'#1769d1',alignItems:'center',padding:14,borderRadius:6}, buttonText:{color:'#fff',fontWeight:'700'}, error:{color:'#b42318',marginBottom:12}, disabled:{opacity:.6} });
