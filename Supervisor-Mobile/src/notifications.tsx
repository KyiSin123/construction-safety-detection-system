import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { Alert, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { api } from './api';
import { useAuth } from './auth';

Notifications.setNotificationHandler({ handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }) });

export function NotificationRegistration() {
  const { token } = useAuth();
  const router = useRouter();
  useEffect(() => {
    const responseSubscription = Notifications.addNotificationResponseReceivedListener(response => {
      const type = response.notification.request.content.data?.type;
      if (type === 'attendance_request') { router.push('/attendance'); return; }
      const id = response.notification.request.content.data?.instance_id;
      if (typeof id === 'string') {
        if (token) api.markRead(token, id).catch(() => undefined);
        router.push(`/violations/${id}`);
      }
    });
    const receivedSubscription = Notifications.addNotificationReceivedListener(notification => {
      const id = notification.request.content.data?.instance_id;
      const type = notification.request.content.data?.type;
      Alert.alert(
        notification.request.content.title || 'PPE safety alert',
        notification.request.content.body || 'A new violation needs review.',
        type === 'attendance_request'
          ? [{ text: 'Later', style: 'cancel' }, { text: 'View', onPress: () => router.push('/attendance') }]
          : typeof id === 'string'
          ? [{ text: 'Later', style: 'cancel' }, { text: 'View', onPress: () => { if (token) api.markRead(token, id).catch(() => undefined); router.push(`/violations/${id}`); } }]
          : [{ text: 'OK' }],
      );
    });
    return () => { responseSubscription.remove(); receivedSubscription.remove(); };
  }, [router, token]);
  useEffect(() => {
    if (!token || !Device.isDevice) return;
    (async () => {
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('safety-alerts', {
          name: 'Safety alerts',
          importance: Notifications.AndroidImportance.HIGH,
          sound: 'default',
          enableVibrate: true,
          vibrationPattern: [0, 250, 250, 250],
        });
      }
      const permissions = await Notifications.getPermissionsAsync();
      const status = permissions.status === 'granted' ? permissions.status : (await Notifications.requestPermissionsAsync()).status;
      if (status !== 'granted') throw new Error('Notification permission was not granted. Enable notifications for PPE Supervisor in Android Settings.');
      const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
      if (!projectId || String(projectId).startsWith('REPLACE_')) throw new Error('The EAS project ID is missing. Rebuild the Android development app after running eas init.');
      const pushToken = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
      await api.device(token, pushToken, Platform.OS);
      Alert.alert('Notifications connected', 'This device can now receive PPE safety alerts.');
    })().catch(error => {
      console.warn(error);
      Alert.alert('Push registration failed', error instanceof Error ? error.message : 'Unable to register this device for push notifications.');
    });
  }, [token]);
  return null;
}
