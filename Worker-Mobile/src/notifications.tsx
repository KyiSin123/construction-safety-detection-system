import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { Alert, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { api } from './api';
import { useAuth } from './auth';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
  }),
});

export function WorkerNotificationRegistration() {
  const { token } = useAuth();
  const router = useRouter();
  useEffect(() => {
    const open = (data: Record<string, unknown>) => {
      const id = data.instance_id;
      if (data.type === 'worker_violation' && typeof id === 'string') router.push(`/proof/${id}`);
    };
    const response = Notifications.addNotificationResponseReceivedListener(value =>
      open(value.notification.request.content.data));
    const received = Notifications.addNotificationReceivedListener(value => {
      const content = value.request.content;
      Alert.alert(content.title || 'Safety action required', content.body || 'Open the app to respond.', [
        { text: 'Later', style: 'cancel' },
        { text: 'View', onPress: () => open(content.data) },
      ]);
    });
    return () => { response.remove(); received.remove(); };
  }, [router]);
  useEffect(() => {
    if (!token || !Device.isDevice) return;
    (async () => {
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('safety-alerts', {
          name: 'Safety alerts', importance: Notifications.AndroidImportance.HIGH,
          sound: 'default', enableVibrate: true, vibrationPattern: [0, 250, 250, 250],
        });
      }
      const current = await Notifications.getPermissionsAsync();
      const status = current.status === 'granted'
        ? current.status : (await Notifications.requestPermissionsAsync()).status;
      if (status !== 'granted') throw new Error('Enable notifications in device settings to receive safety alerts.');
      const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
      if (!projectId) throw new Error('Initialize the Worker app with EAS and rebuild it to enable push notifications.');
      const pushToken = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
      await api.device(token, pushToken, Platform.OS);
    })().catch(error => {
      console.warn(error);
      Alert.alert('Push registration failed', error instanceof Error ? error.message : 'Unable to register notifications.');
    });
  }, [token]);
  return null;
}
