import { Stack } from 'expo-router';
import { Link } from 'expo-router';
import { Text } from 'react-native';
import { AuthProvider } from '../src/auth';
import { NotificationRegistration } from '../src/notifications';

export default function RootLayout() {
  return <AuthProvider><NotificationRegistration /><Stack screenOptions={{ headerStyle: { backgroundColor: '#172033' }, headerTintColor: '#fff', contentStyle: { backgroundColor: '#f4f6f9' } }}><Stack.Screen name="index" options={{ headerShown: false }} /><Stack.Screen name="login" options={{ headerShown: false }} /><Stack.Screen name="violations/index" options={{ title: 'Safety alerts', headerRight: () => <Link href="/attendance"><Text style={{color:'#fff',fontWeight:'700'}}>Attendance</Text></Link> }} /><Stack.Screen name="violations/[id]" options={{ title: 'Violation details' }} /><Stack.Screen name="attendance" options={{ title: 'Attendance requests' }} /><Stack.Screen name="profile" options={{ title: 'Profile' }} /></Stack></AuthProvider>;
}
