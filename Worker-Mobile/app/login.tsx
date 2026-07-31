import { useState } from 'react';
import { Link, Redirect } from 'expo-router';
import { Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useAuth } from '../src/auth';

export default function Login() {
  const { token, signIn } = useAuth();
  const [id, setId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  if (token) return <Redirect href="/violations" />;

  const submit = async () => {
    setError('');
    try {
      await signIn(id, password);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Unable to sign in');
    }
  };

  return (
    <SafeAreaView style={styles.page}>
      <View style={styles.card}>
        <Text style={styles.title}>PPE Worker</Text>
        <Text style={styles.subtitle}>Sign in to respond to your helmet safety alerts.</Text>
        <TextInput style={styles.input} placeholder="Worker ID" autoCapitalize="characters" value={id} onChangeText={setId} />
        <TextInput style={styles.input} placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} />
        <Link href="/forgot-password" asChild>
          <Pressable style={styles.forgot}>
            <Text style={styles.forgotText}>Forgot password?</Text>
          </Pressable>
        </Link>
        {!!error && <Text style={styles.error}>{error}</Text>}
        <Pressable style={styles.button} onPress={submit}>
          <Text style={styles.buttonText}>Sign in</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: 'center', padding: 24, backgroundColor: '#f4f6f9' },
  card: { backgroundColor: '#fff', padding: 24, borderRadius: 8 },
  title: { color: '#172033', fontSize: 28, fontWeight: '700' },
  subtitle: { color: '#637083', marginVertical: 18 },
  input: { borderWidth: 1, borderColor: '#dbe1ea', padding: 12, borderRadius: 6, marginBottom: 12 },
  forgot: { alignSelf: 'flex-end', paddingVertical: 4, marginBottom: 12 },
  forgotText: { color: '#1769d1', fontWeight: '600' },
  button: { backgroundColor: '#1769d1', padding: 14, borderRadius: 6, alignItems: 'center' },
  buttonText: { color: '#fff', fontWeight: '700' },
  error: { color: '#b42318', marginBottom: 10 },
});
