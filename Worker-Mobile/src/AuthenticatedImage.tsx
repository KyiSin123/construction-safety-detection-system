import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, ImageStyle, Platform, StyleProp, Text, View } from 'react-native';
import { API_BASE_URL } from './api';

type Props = { path: string; token: string; style: StyleProp<ImageStyle> };
const absoluteUrl = (path: string) => /^https?:\/\//i.test(path)
  ? path : `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;

export function AuthenticatedImage({ path, token, style }: Props) {
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [error, setError] = useState('');
  const url = absoluteUrl(path);

  useEffect(() => {
    let active = true, objectUrl = '';
    setImageUri(null); setError('');
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(async response => {
        if (!response.ok) throw new Error(`Image unavailable (${response.status})`);
        return response.blob();
      })
      .then(blob => {
        if (Platform.OS === 'web') {
          objectUrl = URL.createObjectURL(blob);
          if (active) setImageUri(objectUrl);
          return;
        }
        const reader = new FileReader();
        reader.onerror = () => {
          if (active) setError('Image could not be decoded');
        };
        reader.onloadend = () => {
          if (active && typeof reader.result === 'string') setImageUri(reader.result);
        };
        reader.readAsDataURL(blob);
      })
      .catch(value => {
        if (active) setError(value instanceof Error ? value.message : 'Image unavailable');
      });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url, token]);

  if (error) return <View style={style}><Text>{error}</Text></View>;
  if (!imageUri) return <View style={style}><ActivityIndicator /></View>;
  return <Image
    source={{ uri: imageUri }}
    style={style} resizeMode="cover" onError={() => setError('Image unavailable')}
  />;
}
