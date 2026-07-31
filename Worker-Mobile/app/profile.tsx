import { useState } from 'react';
import { Alert, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { api } from '../src/api';
import { useAuth } from '../src/auth';
import { AuthenticatedImage } from '../src/AuthenticatedImage';

export default function Profile() {
  const { token, worker, setWorker, signOut } = useAuth();
  const [phone, setPhone] = useState(worker?.phone || '');
  const [email, setEmail] = useState(worker?.email || '');
  const [image, setImage] = useState<string>();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  if (!worker || !token) return null;

  const choosePhoto = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: .75, base64: true,
    });
    if (!result.canceled) setImage(result.assets[0].base64 || undefined);
  };
  const save = async () => {
    setSaving(true);
    try {
      const result = await api.updateProfile(token, { phone, email, image_base64: image });
      setWorker(result.worker);
      setImage(undefined);
      Alert.alert('Saved', result.message);
    } catch (value) {
      Alert.alert('Unable to save', value instanceof Error ? value.message : 'Request failed');
    } finally { setSaving(false); }
  };
  const changePassword = async () => {
    if (next !== confirm) {
      Alert.alert('Passwords do not match');
      return;
    }
    setSaving(true);
    try {
      const result = await api.changePassword(token, current, next);
      setCurrent(''); setNext(''); setConfirm('');
      Alert.alert('Password', result.message);
    } catch (value) {
      Alert.alert('Unable to change password', value instanceof Error ? value.message : 'Request failed');
    } finally { setSaving(false); }
  };
  return <ScrollView contentContainerStyle={styles.page}>
    <View style={styles.card}>
      <Text style={styles.title}>{worker.name}</Text>
      <Text style={styles.hint}>{worker.worker_number} · {worker.team || 'No team'}</Text>
      {image
        ? <Image source={{ uri: `data:image/jpeg;base64,${image}` }} style={styles.photo} />
        : worker.has_profile_photo
          ? <AuthenticatedImage path="/api/worker/profile-photo" token={token} style={styles.photo} />
          : <View style={[styles.photo, styles.placeholder]}><Text>No photo</Text></View>}
      <Pressable onPress={choosePhoto}><Text style={styles.link}>Choose profile photo</Text></Pressable>
      <TextInput style={styles.input} value={phone} onChangeText={setPhone} placeholder="Phone" />
      <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="Email" autoCapitalize="none" keyboardType="email-address" />
      <Pressable style={styles.button} onPress={save} disabled={saving}><Text style={styles.white}>Save profile</Text></Pressable>
    </View>
    <View style={styles.card}>
      <Text style={styles.title}>Change password</Text>
      <TextInput style={styles.input} value={current} onChangeText={setCurrent} placeholder="Current password" secureTextEntry />
      <TextInput style={styles.input} value={next} onChangeText={setNext} placeholder="New password" secureTextEntry />
      <TextInput style={styles.input} value={confirm} onChangeText={setConfirm} placeholder="Confirm new password" secureTextEntry />
      <Text style={styles.hint}>At least 8 characters with a letter and number.</Text>
      <Pressable style={styles.button} onPress={changePassword} disabled={saving}><Text style={styles.white}>Change password</Text></Pressable>
    </View>
    <Pressable style={styles.signout} onPress={signOut}><Text style={styles.white}>Sign out</Text></Pressable>
  </ScrollView>;
}

const styles = StyleSheet.create({
  page:{padding:16,gap:12,paddingBottom:30},
  card:{backgroundColor:'#fff',padding:18,borderRadius:8,borderWidth:1,borderColor:'#dbe1ea'},
  title:{fontSize:20,fontWeight:'700'},
  hint:{color:'#637083',marginTop:5},
  photo:{width:110,height:110,borderRadius:55,alignSelf:'center',marginVertical:14},
  placeholder:{backgroundColor:'#e9eef5',justifyContent:'center',alignItems:'center'},
  link:{color:'#1769d1',fontWeight:'700',textAlign:'center'},
  input:{borderWidth:1,borderColor:'#dbe1ea',padding:12,borderRadius:6,marginTop:11},
  button:{backgroundColor:'#1769d1',padding:13,borderRadius:6,alignItems:'center',marginTop:13},
  white:{color:'#fff',fontWeight:'700'},
  signout:{backgroundColor:'#b42318',padding:13,borderRadius:6,alignItems:'center'},
});
