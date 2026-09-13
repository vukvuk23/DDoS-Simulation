import { useEffect, useRef, useState } from 'react';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { NOTIFIER_BASE_URL } from './config';


Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});


export function usePushNotifications() {

  const [lastNotification, setLastNotification] = useState(null);
  const listenerRef = useRef();

  useEffect(() => {

    registerForPushNotifications();

    listenerRef.current = Notifications.addNotificationReceivedListener(
      (notification) => {
        setLastNotification(notification.request.content);
      }
    );

    return () => {
      if (listenerRef.current) {
        Notifications.removeNotificationSubscription(listenerRef.current);
      }
    };
  }, []);

  return { lastNotification };
}


async function registerForPushNotifications() {

  if (!Device.isDevice) {
    console.log('Push notifikacije zahtevaju fizicki uredjaj.');
    return;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    console.log('Korisnik nije dozvolio notifikacije.');
    return;
  }

  const projectId = Constants.expoConfig?.extra?.eas?.projectId;

  const tokenResponse = await Notifications.getExpoPushTokenAsync({ projectId });
  const pushToken = tokenResponse.data;

  console.log('Dobijen Expo push token:', pushToken);

  try {
    await fetch(`${NOTIFIER_BASE_URL}/api/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ push_token: pushToken }),
    });
  } catch (e) {
    console.log('Registracija tokena nije uspela:', e);
  }
}