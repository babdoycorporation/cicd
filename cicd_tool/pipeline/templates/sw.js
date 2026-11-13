// CogFocus One™ CI/CD — Service Worker for Web Push Notifications
const CACHE_NAME = 'cogfocus-sw-v1';

self.addEventListener('install', function(event) {
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    event.waitUntil(self.clients.claim());
});

// Handle Background Push Event
self.addEventListener('push', function(event) {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch (e) {
            payload = { title: 'CogFocus One Notification', content: event.data.text() };
        }
    }
    const title = payload.title || 'New Pull Request';
    const options = {
        body: payload.content || payload.body || 'A new pull request was raised.',
        icon: payload.icon || '/static/images/logo/cogfocus_favicon_180x180.png',
        badge: payload.badge || '/static/images/logo/cogfocus_favicon_180x180.png',
        tag: payload.tag || ('notif-' + Date.now()),
        data: { url: payload.link || payload.url || '/notifications/' },
        requireInteraction: true,
        vibrate: [200, 100, 200]
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

// Handle Notification Click
self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) 
        ? event.notification.data.url 
        : '/notifications/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
            for (let i = 0; i < windowClients.length; i++) {
                const client = windowClients[i];
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});

