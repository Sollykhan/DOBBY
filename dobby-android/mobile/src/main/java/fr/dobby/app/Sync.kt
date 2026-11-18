package fr.dobby.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONArray
import org.json.JSONObject

object Alerts {
    private const val CHANNEL = "dobby_missions"
    fun notify(context: Context, id: String, text: String) {
        if (android.os.Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Missions DOBBY", NotificationManager.IMPORTANCE_DEFAULT))
        val intent = Intent(context, MainActivity::class.java).putExtra("mission_id", id)
        val pending = PendingIntent.getActivity(context, id.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("DOBBY · votre attention est demandée").setContentText(text)
            .setContentIntent(pending).setAutoCancel(true).build()
        manager.notify(id.hashCode(), notification)
    }
}

object WearSync {
    suspend fun publish(context: Context, missions: List<Mission>) {
        val items = JSONArray()
        missions.take(5).forEach { items.put(JSONObject().put("id", it.id).put("state", it.state).put("mode", it.mode)) }
        val payload = JSONObject().put("connected", true).put("missions", items).toString().toByteArray()
        Wearable.getNodeClient(context).connectedNodes.await().forEach { node ->
            try { Wearable.getMessageClient(context).sendMessage(node.id, "/dobby/snapshot", payload).await() } catch (_: Exception) { }
        }
    }
}

object VoiceWithCalendars {
    suspend fun ask(context: Context, backend: Backend, question: String): String {
        val selected = context.getSharedPreferences("dobby_calendars", Context.MODE_PRIVATE).getStringSet("selected", emptySet()) ?: emptySet()
        if (selected.isEmpty()) return backend.voice(question)
        val plan = backend.calendarPlan(question)
        if (!plan.optBoolean("calendar", false)) return backend.voice(question)
        val events = kotlinx.coroutines.withContext(Dispatchers.IO) { LocalCalendarReader.selectedEvents(context, plan.getString("start"), plan.getString("end")) }
        return backend.voice(question, events)
    }
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val session = Vault(applicationContext).load() ?: return Result.success()
        return try {
            val missions = Backend(session.first, session.second).missions()
            val seen = applicationContext.getSharedPreferences("notification_state", Context.MODE_PRIVATE)
            missions.forEach {
                val marker = "${it.state}:${it.turns}"
                if (it.state == "awaiting_approval" && seen.getString(it.id, "") != marker) Alerts.notify(applicationContext, it.id, "Une mission attend votre approbation.")
                seen.edit().putString(it.id, marker).apply()
            }
            try { WearSync.publish(applicationContext, missions) } catch (_: Exception) { }
            Result.success()
        } catch (_: Exception) { Result.retry() }
    }
}

class WearBridgeService : WearableListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    override fun onMessageReceived(event: MessageEvent) {
        scope.launch {
            val paired = try { Wearable.getNodeClient(this@WearBridgeService).connectedNodes.await().any { it.id == event.sourceNodeId } } catch (_: Exception) { false }
            if (!paired) return@launch
            when (event.path) {
                "/dobby/voice" -> {
                    val obj = try { if (event.data.size > 4096) return@launch; JSONObject(String(event.data, Charsets.UTF_8)) } catch (_: Exception) { return@launch }
                    val id = obj.optString("id")
                    val question = obj.optString("question")
                    if (!Regex("^[0-9a-f-]{36}$").matches(id) || question.isBlank() || question.length > 500) return@launch
                    val session = Vault(this@WearBridgeService).load()
                    var canSpeak = false
                    val response = try {
                        if (session == null) "Connectez-vous à DOBBY sur le téléphone."
                        else {
                            VoiceWithCalendars.ask(this@WearBridgeService, Backend(session.first, session.second), question).also { canSpeak = obj.optBoolean("want_audio", false) }
                        }
                    } catch (_: Exception) { "Serveur indisponible ou session expirée. Vérifiez DOBBY sur le téléphone." }
                    val payload = JSONObject().put("id", id).put("reply", response).put("audio_pending", canSpeak).toString().toByteArray(Charsets.UTF_8)
                    try { Wearable.getMessageClient(this@WearBridgeService).sendMessage(event.sourceNodeId, "/dobby/voice-result", payload).await() } catch (_: Exception) { return@launch }
                    if (canSpeak && session != null) {
                        try {
                            val language = obj.optString("audio_language", "fr").takeIf { it == "fr" || it == "en" } ?: "fr"
                            val audio = Backend(session.first, session.second).speech(response, language)
                            val client = Wearable.getChannelClient(this@WearBridgeService)
                            val channel = client.openChannel(event.sourceNodeId, "/dobby/audio/" + id).await()
                            var sent = false
                            try { client.getOutputStream(channel).await().use { it.write(audio); it.flush() }; sent = true }
                            finally { if (!sent) try { client.close(channel).await() } catch (_: Exception) { } }
                            // The receiver closes the channel after consuming the stream.
                            // Keep a bounded cleanup for the case where it disappears.
                            kotlinx.coroutines.delay(45000)
                            try { client.close(channel).await() } catch (_: Exception) { }
                        } catch (_: Exception) {
                            try { Wearable.getMessageClient(this@WearBridgeService).sendMessage(event.sourceNodeId, "/dobby/audio-error", id.toByteArray(Charsets.UTF_8)).await() } catch (_: Exception) { }
                        }
                    }
                }
                "/dobby/refresh" -> {
                    val session = Vault(this@WearBridgeService).load() ?: return@launch
                    try { WearSync.publish(this@WearBridgeService, Backend(session.first, session.second).missions()) } catch (_: Exception) { }
                }
                "/dobby/request-approval" -> {
                    // A watch request never executes an approval: unlock the phone and confirm there.
                    val id = try { Endpoint.missionId(String(event.data, Charsets.UTF_8)) } catch (_: Exception) { return@launch }
                    Alerts.notify(this@WearBridgeService, id, "Demande depuis la montre : ouvrez DOBBY sur le téléphone pour confirmer.")
                }
            }
        }
    }
}
