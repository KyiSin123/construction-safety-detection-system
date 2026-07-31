import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, ImageStyle, Platform, StyleProp, Text, View } from 'react-native';
import { API_BASE_URL } from './api';

type Props = { path: string; token: string; style: StyleProp<ImageStyle> };
const absoluteUrl = (path: string) => /^https?:\/\//i.test(path)
  ? path : `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;

export function AuthenticatedImage({ path, token, style }: Props) {
  const [webUri, setWebUri] = useState<string | null>(null);
  const [error, setError] = useState('');
  const url = absoluteUrl(path);

  useEffect(() => {
    if (Platform.OS !== 'web') return;
    let active = true, objectUrl = '';
    setWebUri(null); setError('');
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(async response => {
        if (!response.ok) throw new Error(`Image unavailable (${response.status})`);
        return response.blob();
      })
      .then(blob => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setWebUri(objectUrl);
      })
      .catch(value => {
        if (active) setError(value instanceof Error ? value.message : 'Image unavailable');
      });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url, token]);

  if (error) return <View style={style}><Text>{error}</Text></View>;
  if (Platform.OS === 'web' && !webUri) return <View style={style}><ActivityIndicator /></View>;
  return <Image
    source={Platform.OS === 'web' ? { uri: webUri as string } : { uri: url, headers: { Authorization: `Bearer ${token}` } }}
    style={style} resizeMode="cover" onError={() => setError('Image unavailable')}
  />;
}
