// firebase-messaging-sw.js
// Uygulama kapalıyken (arka planda) push bildirimlerini karşılar.
// Bu dosya KÖK dizinde olmalı (index.html ile aynı seviyede).

importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-messaging-compat.js');

// index.html içindeki firebaseConfig ile AYNI olmalı
firebase.initializeApp({
  apiKey: "AIzaSyAUdkTkbut1KrO-IAOPGfAUG0fx0YCvY2A",
  authDomain: "bist100-scanner.firebaseapp.com",
  projectId: "bist100-scanner",
  storageBucket: "bist100-scanner.firebasestorage.app",
  messagingSenderId: "1034148308576",
  appId: "1:1034148308576:web:e6b5a87fa5d34a45924505"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const title = payload.notification?.title || "BIST100 Sinyal";
  const options = {
    body: payload.notification?.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    data: payload.data,
  };
  self.registration.showNotification(title, options);
});
