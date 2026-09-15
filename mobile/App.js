import React, { useState } from 'react';
import { View, Text, Pressable, StyleSheet, Alert } from 'react-native';
import { SafeAreaView, SafeAreaProvider } from 'react-native-safe-area-context';
import { usePushNotifications } from './src/usePushNotifications';
import { triggerScaleUp, triggerRateLimit } from './src/api';


export default function App() {

  const { lastNotification } = usePushNotifications();
  const [busy, setBusy] = useState(false);

  async function handleScaleUp() {
    setBusy(true);
    try {
      await triggerScaleUp();
      Alert.alert('Uspesno', 'Poslata komanda za scale up.');
    } catch (e) {
      Alert.alert('Greska', e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRateLimit() {
    setBusy(true);
    try {
      await triggerRateLimit();
      Alert.alert('Uspesno', 'Rate limit je pojacan.');
    } catch (e) {
      Alert.alert('Greska', e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleStrictRateLimit() {
    setBusy(true);
    try {
      await triggerRateLimit(5, 5);
      Alert.alert('Uspesno', 'Strozi rate limit je postavljen (5 req/s).');
    } catch (e) {
      Alert.alert('Greska', e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.container}>
        <Text style={styles.title}>DDoS Odbrana</Text>

        <View style={styles.statusBox}>
          <Text style={styles.statusLabel}>Poslednja notifikacija:</Text>
          <Text style={styles.statusText}>
            {lastNotification
              ? `${lastNotification.title}\n${lastNotification.body}`
              : 'Jos uvek nema notifikacija.'}
          </Text>
        </View>

        <Pressable
          style={[styles.button, styles.scaleButton]}
          onPress={handleScaleUp}
          disabled={busy}
        >
          <Text style={styles.buttonText}>Scale Up</Text>
        </Pressable>

        <Pressable
          style={[styles.button, styles.rateLimitButton]}
          onPress={handleRateLimit}
          disabled={busy}
        >
          <Text style={styles.buttonText}>Rate Limit</Text>
        </Pressable>

        <Pressable
          style={[styles.button, styles.strictRateLimitButton]}
          onPress={handleStrictRateLimit}
          disabled={busy}
        >
          <Text style={styles.buttonText}>Rate Limit (strozi)</Text>
        </Pressable>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}


const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1C1F22',
    padding: 24,
    justifyContent: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: '600',
    color: '#FFFFFF',
    marginBottom: 24,
    textAlign: 'center',
  },
  statusBox: {
    backgroundColor: '#2A2D30',
    borderRadius: 10,
    padding: 16,
    marginBottom: 32,
  },
  statusLabel: {
    color: '#667085',
    fontSize: 12,
    marginBottom: 8,
  },
  statusText: {
    color: '#FFFFFF',
    fontSize: 15,
  },
  button: {
    borderRadius: 8,
    paddingVertical: 16,
    alignItems: 'center',
    marginBottom: 16,
  },
  scaleButton: {
    backgroundColor: '#1F6F5C',
  },
  rateLimitButton: {
    backgroundColor: '#B33A3A',
  },
  strictRateLimitButton: {
    backgroundColor: '#7A1F1F',
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
});