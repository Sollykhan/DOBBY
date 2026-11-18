package fr.dobby.watch

import android.content.Context
import android.media.AudioAttributes
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale
import android.util.Log

class VoiceOutput(private val context: Context, private val report: (String) -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private var engine: TextToSpeech? = null
    private var ready = false
    private var failed = false
    private var closed = false
    private var pending: String? = null
    @Volatile private var finalUtteranceId: String? = null

    init {
        initialize(null)
    }

    private fun initialize(engineName: String?) {
        engine = TextToSpeech(context, { status -> main.post {
            Log.i("DobbyVoice", "tts init=$status engine=${engine?.defaultEngine ?: "none"}")
            if (closed) return@post
            val tts = engine
            if (status != TextToSpeech.SUCCESS || tts == null) {
                if (engineName == null) {
                    tts?.shutdown(); engine = null
                    report("Recherche d’une voix française…")
                    initialize("com.google.android.tts")
                } else { failed = true; pending = null; report("Synthèse vocale indisponible") }
                return@post
            }
            val language = tts.setLanguage(Locale.FRANCE)
            Log.i("DobbyVoice", "tts locale_france=$language")
            if (language == TextToSpeech.LANG_MISSING_DATA || language == TextToSpeech.LANG_NOT_SUPPORTED) {
                if (engineName == null && tts.defaultEngine != "com.google.android.tts" && tts.engines.any { it.name == "com.google.android.tts" }) {
                    Log.i("DobbyVoice", "tts french unavailable; trying installed Google engine for app")
                    tts.shutdown(); engine = null; report("Recherche d’une voix française…"); initialize("com.google.android.tts"); return@post
                }
                failed = true; pending = null; report("Voix française indisponible ($language)"); return@post
            }
            val offline = tts.voices?.filter { it.locale.language == Locale.FRENCH.language && !it.isNetworkConnectionRequired && it.features?.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) != true }
                ?.sortedWith(compareByDescending<android.speech.tts.Voice> { it.locale.country == Locale.FRANCE.country }.thenBy { it.latency }.thenByDescending { it.quality })
                ?.firstOrNull()
            if (offline != null) {
                val voiceResult = tts.setVoice(offline)
                Log.i("DobbyVoice", "tts offline_french_selected=$voiceResult latency=${offline.latency}")
            } else Log.i("DobbyVoice", "tts offline_french_unavailable")
            if (tts.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()) != TextToSpeech.SUCCESS) { failed = true; pending = null; report("Configuration audio impossible"); return@post }
            tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(id: String?) { Log.i("DobbyVoice", "tts onStart"); main.post { if (!closed) report("Lecture vocale démarrée") } }
                override fun onDone(id: String?) { Log.i("DobbyVoice", "tts onDone"); if (id == finalUtteranceId) main.post { if (!closed && id == finalUtteranceId) report("Lecture terminée") } }
                @Deprecated("Deprecated in Android") override fun onError(id: String?) { main.post { if (!closed) report("Erreur de synthèse vocale") } }
                override fun onError(id: String?, errorCode: Int) { Log.w("DobbyVoice", "tts onError=$errorCode"); main.post { if (!closed) report("Erreur de synthèse vocale ($errorCode)") } }
            })
            ready = true
            pending?.let { pending = null; speak(it) }
        } }, engineName)
    }

    fun speak(text: String) {
        if (failed) { report("Voix indisponible : vérifiez le moteur et le français"); return }
        if (!ready) { pending = text; report("Préparation de la voix…"); return }
        val parts = mutableListOf<String>()
        var remaining = text.trim()
        while (remaining.isNotEmpty()) {
            if (remaining.length <= 100) { parts.add(remaining); break }
            val lastSpace = remaining.lastIndexOf(' ', 100)
            val cut = if (lastSpace >= 35) lastSpace else 100
            parts.add(remaining.substring(0, cut).trim())
            remaining = remaining.substring(cut).trimStart()
        }
        val base = System.nanoTime()
        finalUtteranceId = "dobby-$base-${parts.lastIndex}"
        for ((index, part) in parts.withIndex()) {
            val result = engine?.speak(part, if (index == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD, null, "dobby-$base-$index")
            Log.i("DobbyVoice", "tts speak=$result chunk=$index")
            if (result != TextToSpeech.SUCCESS) { engine?.stop(); report("Lecture vocale refusée"); return }
        }
    }

    fun close() { closed = true; pending = null; engine?.stop(); engine?.shutdown(); engine = null }
}
