import { ActivityIndicator, View } from 'react-native';
import { Redirect } from 'expo-router';
import { useAuth } from '../src/auth';
export default function Index() { const { loading, token } = useAuth(); if (loading) return <View style={{ flex: 1, justifyContent: 'center' }}><ActivityIndicator /></View>; return <Redirect href={token ? '/violations' : '/login'} />; }
