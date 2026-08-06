importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-messaging-compat.js');

// FIREBASE KONFİGÜRASYONU
firebase.initializeApp({
  apiKey: "AIzaSyAUdkTkbut1KrO-IAOPGfAUG0fx0YCvY2A",
  authDomain: "bist100-scanner.firebaseapp.com",
  projectId: "bist100-scanner",
  storageBucket: "bist100-scanner.firebasestorage.app",
  messagingSenderId: "1034148308576",
  appId: "1:1034148308576:web:e6b5a87fa5d34a45924505"
});

const messaging = firebase.messaging();

// Arka Plan Bildirim Yakalayıcı
messaging.onBackgroundMessage((payload) => {
  console.log('[firebase-messaging-sw.js] Arka plan bildirimi alındı:', payload);

  const notificationTitle = payload.notification ? payload.notification.title : 'BIST100 Sinyal Uyarısı';
  const notificationOptions = {
    body: payload.notification ? payload.notification.body : 'Yeni bir sinyal veya portföy uyarısı mevcut.',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png'
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});
