package fr.dobby.watch

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService
import org.json.JSONObject

class SnapshotService : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        if (event.path != "/dobby/snapshot" || event.data.size > 8192) return
        try {
            val list = JSONObject(String(event.data)).getJSONArray("missions")
            val last = if (list.length() > 0) list.getJSONObject(0).optString("state", "inconnu") else "aucune"
            val count = (0 until minOf(list.length(), 5)).count { list.getJSONObject(it).optString("state") == "awaiting_approval" }
            getSharedPreferences("dobby_tile", MODE_PRIVATE).edit().putLong("received", System.currentTimeMillis()).putString("last", last).putInt("pending", count).apply()
            androidx.wear.tiles.TileService.getUpdater(this).requestUpdate(DobbyTileService::class.java)
            if (android.os.Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
            val pending = (0 until minOf(list.length(), 5)).any { list.getJSONObject(it).optString("state") == "awaiting_approval" }
            if (!pending) return
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("dobby_watch", "Missions DOBBY", NotificationManager.IMPORTANCE_DEFAULT))
            val intent = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val n = NotificationCompat.Builder(this, "dobby_watch").setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("DOBBY").setContentText("Une mission attend votre attention.").setContentIntent(intent).setAutoCancel(true).build()
            manager.notify(1, n)
        } catch (_: Exception) { }
    }
}
