import { Link } from 'expo-router';
import { Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';

export default function ForgotPassword() {
  return (
    <SafeAreaView style={styles.page}>
      <View style={styles.card}>
        <Text style={styles.title}>Forgot your password?</Text>
        <Text style={styles.body}>
          Ask your supervisor or site administrator to reset your password. Provide your worker ID
          so they can find the correct account.
        </Text>
        <Text style={styles.note}>
          The administrator can set a new password from Admin dashboard → Worker registry.
        </Text>
        <Link href="/login" asChild>
          <Pressable style={styles.button}>
            <Text style={styles.buttonText}>Back to sign in</Text>
          </Pressable>
        </Link>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: 'center', padding: 24, backgroundColor: '#f4f6f9' },
  card: { backgroundColor: '#fff', padding: 24, borderRadius: 8 },
  title: { color: '#172033', fontSize: 24, fontWeight: '700', marginBottom: 14 },
  body: { color: '#334155', fontSize: 16, lineHeight: 24 },
  note: { color: '#637083', lineHeight: 21, marginTop: 14, marginBottom: 22 },
  button: { backgroundColor: '#1769d1', alignItems: 'center', padding: 14, borderRadius: 6 },
  buttonText: { color: '#fff', fontWeight: '700' },
});
