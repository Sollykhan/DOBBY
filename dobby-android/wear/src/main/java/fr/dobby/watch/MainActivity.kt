package fr.dobby.watch

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.content.Intent
import android.app.Activity
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.RecognitionListener
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.delay
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.google.android.gms.wearable.MessageClient
import com.google.android.gms.wearable.ChannelClient
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONObject

data class WatchMission(val id: String, val state: String)

class MainActivity : ComponentActivity() {
    private var listenRequest by mutableIntStateOf(0)
    private var pendingListen = false
    private fun acceptListen(intent: Intent?) {
        if (consumeListenRequest(intent)) pendingListen = true
    }
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); if (savedInstanceState == null) acceptListen(intent); androidx.wear.tiles.TileService.getUpdater(this).requestUpdate(DobbyTileService::class.java); setContent { WatchScreen(this, listenRequest) } }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); acceptListen(intent) }
    override fun onPostResume() { super.onPostResume(); if (pendingListen) { pendingListen = false; listenRequest++ } }
}

@Composable private fun WatchScreen(activity: MainActivity, listenRequest: Int) {
    var state by remember { mutableStateOf("Téléphone non connecté") }
    var missions by remember { mutableStateOf<List<WatchMission>>(emptyList()) }
    var confirm by remember { mutableStateOf<String?>(null) }
    var reply by remember { mutableStateOf("") }
    var pendingId by remember { mutableStateOf<String?>(null) }
    var audioPendingId by remember { mutableStateOf<String?>(null) }
    var expectedNode by remember { mutableStateOf<String?>(null) }
    var activeAudioChannel by remember { mutableStateOf<ChannelClient.Channel?>(null) }
    val scope = rememberCoroutineScope()
    val client = remember { Wearable.getMessageClient(activity) }
    var voiceStatus by remember { mutableStateOf("") }
    val tts = remember { VoiceOutput(activity) { voiceStatus = it } }
    val voicePrefs = remember { activity.getSharedPreferences("dobby_voice", android.content.Context.MODE_PRIVATE) }
    var voiceEnabled by remember { mutableStateOf(voicePrefs.getBoolean("enabled", true)) }
    var audioLanguage by remember { mutableStateOf(voicePrefs.getString("language", "fr") ?: "fr") }
    val audioPlayer = remember { WatchAudioPlayer(activity) }
    var recognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }
    var localOnly by remember { mutableStateOf(false) }
    DisposableEffect(tts) { onDispose { recognizer?.cancel(); recognizer?.destroy(); tts.close(); audioPlayer.close() } }
    fun sendWords(words: String) {
            if (words.isBlank() || words.length > 500) { state = "Question invalide"; return }
            if (localOnly) { reply = words; state = "Transcription locale"; localOnly = false; return }
            val id = UUID.randomUUID().toString(); pendingId = id; state = "Traitement…"; reply = ""
            scope.launch {
                try {
                    val nodes = Wearable.getNodeClient(activity).connectedNodes.await()
                    if (nodes.size != 1) { pendingId = null; state = "Téléphone indisponible"; return@launch }
                    expectedNode = nodes.single().id
                    client.sendMessage(nodes.single().id, "/dobby/voice", JSONObject().put("id", id).put("question", words).put("want_audio", voiceEnabled).put("audio_language", audioLanguage).toString().toByteArray(Charsets.UTF_8)).await()
                    delay(25000)
                    if (pendingId == id) { pendingId = null; state = "Délai dépassé" }
                } catch (_: Exception) { pendingId = null; state = "Connexion indisponible" }
            }
    }
    val fallback = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) sendWords(result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty().trim())
        else { localOnly = false; state = "Écoute annulée" }
    }
    fun startListening() {
        if (recognizer != null) { state = "Écoute déjà en cours"; return }
        if (!SpeechRecognizer.isRecognitionAvailable(activity)) { state = "Reconnaissance vocale indisponible"; return }
        try {
            val r = SpeechRecognizer.createSpeechRecognizer(activity)
            recognizer = r
            r.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) { Log.i("DobbyVoice", "recognition ready"); state = "Écoute…" }
                override fun onBeginningOfSpeech() { Log.i("DobbyVoice", "recognition beginning"); state = "Je vous écoute…" }
                override fun onRmsChanged(value: Float) { }
                override fun onBufferReceived(buffer: ByteArray?) { }
                override fun onEndOfSpeech() { state = "Transcription…" }
                override fun onError(error: Int) {
                    Log.w("DobbyVoice", "recognition error=$error")
                    r.destroy(); recognizer = null
                    if (error == SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED || error == SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE || error == SpeechRecognizer.ERROR_CLIENT) {
                        try { state = "Ouverture de la saisie vocale…"; fallback.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM).putExtra(RecognizerIntent.EXTRA_PROMPT, "Posez votre question")) }
                        catch (_: Exception) { localOnly = false; state = "Saisie vocale indisponible ($error)" }
                    } else { localOnly = false; state = "Écoute impossible ($error)" }
                }
                override fun onResults(results: Bundle?) { Log.i("DobbyVoice", "recognition results"); val words = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim(); r.destroy(); recognizer = null; sendWords(words) }
                override fun onPartialResults(results: Bundle?) { }
                override fun onEvent(eventType: Int, params: Bundle?) { }
            })
            state = "Connexion au micro…"
            r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM).putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fr-FR").putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1))
        } catch (_: Exception) { recognizer?.destroy(); recognizer = null; state = "Reconnaissance vocale indisponible" }
    }
    val microphone = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) startListening() else state = "Autorisez le microphone pour écouter" }
    LaunchedEffect(listenRequest) { if (listenRequest > 0) { if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startListening() else microphone.launch(Manifest.permission.RECORD_AUDIO) } }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val listener = remember { MessageClient.OnMessageReceivedListener { event ->
        if (event.path == "/dobby/audio-error" && event.sourceNodeId == expectedNode && String(event.data, Charsets.UTF_8) == audioPendingId) {
            audioPendingId = null; if (voiceEnabled) tts.speak(reply)
        } else if (event.path == "/dobby/voice-result" && event.sourceNodeId == expectedNode && event.data.size <= 4096) {
            try {
                val result = JSONObject(String(event.data, Charsets.UTF_8))
                if (pendingId != null && result.optString("id") == pendingId) {
                    val answer = result.getString("reply")
                    if (answer.length <= 500) { pendingId = null; reply = answer; state = "Réponse reçue"; if (voiceEnabled && result.optBoolean("audio_pending", false)) audioPendingId = result.getString("id") else if (voiceEnabled) tts.speak(answer) }
                }
            } catch (_: Exception) { state = "Réponse invalide" }
        } else if (event.path == "/dobby/snapshot") {
            try {
                val obj = JSONObject(String(event.data)); val items = obj.getJSONArray("missions")
                missions = (0 until minOf(items.length(), 5)).map { i -> items.getJSONObject(i).let { WatchMission(it.getString("id"), it.getString("state")) } }
                state = "Téléphone connecté"
            } catch (_: Exception) { state = "Données indisponibles" }
        }
    } }
    DisposableEffect(client) { client.addListener(listener); onDispose { client.removeListener(listener) } }
    val channelClient = remember { Wearable.getChannelClient(activity) }
    val channelCallback = remember { object : ChannelClient.ChannelCallback() {
        override fun onChannelOpened(channel: ChannelClient.Channel) {
            val id = channel.path.removePrefix("/dobby/audio/")
            if (!channel.path.startsWith("/dobby/audio/") || channel.nodeId != expectedNode || (id != audioPendingId && id != pendingId)) { channelClient.close(channel); return }
            activeAudioChannel = channel
            scope.launch {
                try {
                    val bytes = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                        channelClient.getInputStream(channel).await().use { input ->
                            val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                            while (true) { val n = input.read(buffer); if (n < 0) break; require(out.size() + n <= 3 * 1024 * 1024); out.write(buffer, 0, n) }
                            out.toByteArray()
                        }
                    }
                    repeat(50) { if (audioPendingId == id || pendingId != id) return@repeat; delay(100) }
                    if (audioPendingId == id && voiceEnabled) {
                        require(bytes.size >= 12 && String(bytes, 0, 4, Charsets.US_ASCII) == "RIFF" && String(bytes, 8, 4, Charsets.US_ASCII) == "WAVE")
                        audioPendingId = null
                        audioPlayer.play(bytes, { if (voiceEnabled) tts.speak(reply) }, { })
                    }
                } catch (_: Exception) { if (audioPendingId == id) { audioPendingId = null; if (voiceEnabled) tts.speak(reply) } }
                finally { if (activeAudioChannel == channel) activeAudioChannel = null; try { channelClient.close(channel).await() } catch (_: Exception) { } }
            }
        }
    } }
    DisposableEffect(channelClient) { channelClient.registerChannelCallback(channelCallback); onDispose { activeAudioChannel?.let { channelClient.close(it) }; channelClient.unregisterChannelCallback(channelCallback) } }
    LaunchedEffect(audioPendingId) {
        val id = audioPendingId
        if (id != null) { delay(45000); if (audioPendingId == id) { audioPendingId = null; activeAudioChannel?.let { channelClient.close(it) }; if (voiceEnabled) tts.speak(reply) } }
    }
    suspend fun send(path: String, bytes: ByteArray = byteArrayOf()) {
        try {
            val nodes = Wearable.getNodeClient(activity).connectedNodes.await()
            if (nodes.isEmpty()) { state = "Téléphone non connecté"; return }
            nodes.forEach { client.sendMessage(it.id, path, bytes).await() }
        } catch (_: Exception) { state = "Synchronisation indisponible" }
    }
    LaunchedEffect(Unit) {
        if (android.os.Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(activity, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        send("/dobby/refresh")
    }
    MaterialTheme {
        LazyColumn(Modifier.fillMaxSize().background(Color.Black).padding(horizontal = 18.dp), contentPadding = PaddingValues(vertical = 20.dp)) {
            item { Text("✦ DOBBY", color = Color(0xFF55DFFF), fontSize = 20.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth()); Text(state, fontSize = 11.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) }
            if (voiceStatus.isNotEmpty()) item { Text(voiceStatus, fontSize = 10.sp, color = Color(0xFFA8D4EB), textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth()) }
            item {
                Box(Modifier.fillMaxWidth(), contentAlignment = androidx.compose.ui.Alignment.Center) {
                    Button(onClick = { if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startListening() else microphone.launch(Manifest.permission.RECORD_AUDIO) }, modifier = Modifier.size(90.dp).border(1.dp, Color(0xFF55DFFF), CircleShape), colors = androidx.wear.compose.material.ButtonDefaults.buttonColors(backgroundColor = Color(0xFF082341))) { Text("◉\nÉcouter", fontSize = 13.sp, textAlign = TextAlign.Center, color = Color(0xFFBDEFFF)) }
                }
                if (reply.isNotEmpty()) Text(reply, fontSize = 11.sp, color = Color(0xFF55DFFF), textAlign = TextAlign.Center)
            }
            item { Button(onClick = { tts.speak("Bonjour, je suis Dobby. Je suis à votre écoute.") }) { Text("Tester la voix", fontSize = 10.sp) } }
            item { Button(onClick = { localOnly = true; if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startListening() else microphone.launch(Manifest.permission.RECORD_AUDIO) }) { Text("Test micro local", fontSize = 10.sp) } }
            item { Button(onClick = { voiceEnabled = !voiceEnabled; voicePrefs.edit().putBoolean("enabled", voiceEnabled).apply() }) { Text(if (voiceEnabled) "Voix activée" else "Voix désactivée", fontSize = 10.sp) } }
            item { Button(onClick = { audioLanguage = if (audioLanguage == "fr") "en" else "fr"; voicePrefs.edit().putString("language", audioLanguage).apply() }) { Text(if (audioLanguage == "fr") "Voix : Tom (français)" else "Voix : Alan (anglais)", fontSize = 10.sp) } }
            items(missions) { mission ->
                Text("Mission · ${mission.state}", fontSize = 12.sp, modifier = Modifier.padding(vertical = 4.dp))
                if (mission.state == "awaiting_approval") {
                    if (confirm == mission.id) Button(onClick = { scope.launch { send("/dobby/request-approval", mission.id.toByteArray()); confirm = null; state = "Confirmez sur le téléphone" } }) { Text("Confirmer la demande", fontSize = 10.sp) }
                    else Button(onClick = { confirm = mission.id }) { Text("Demander approbation", fontSize = 10.sp) }
                }
            }
            item { Spacer(Modifier.height(8.dp)); Button(onClick = { scope.launch { state = "Actualisation…"; send("/dobby/refresh") } }, modifier = Modifier.fillMaxWidth().height(42.dp).border(1.dp, Color(0xFF217BA8), RoundedCornerShape(22.dp)), colors = androidx.wear.compose.material.ButtonDefaults.buttonColors(backgroundColor = Color(0xFF071829))) { Text("↻  Actualiser", fontSize = 11.sp, color = Color(0xFF9AE8FF)) } }
        }
    }
}
