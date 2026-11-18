package fr.dobby.watch

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import java.io.File

/** Audio stays in private cache only while playing; no user text is logged. */
class WatchAudioPlayer(private val context: Context) {
    private var player: MediaPlayer? = null
    private var audioFile: File? = null

    init { context.cacheDir.listFiles()?.filter { it.isFile && it.name.startsWith("dobby_voice_") && it.name.endsWith(".wav") }?.forEach { it.delete() } }

    fun play(bytes: ByteArray, failed: () -> Unit, completed: () -> Unit) {
        close()
        try {
            val file = File.createTempFile("dobby_voice_", ".wav", context.cacheDir)
            audioFile = file
            file.writeBytes(bytes)
            val p = MediaPlayer()
            player = p
            p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(file.absolutePath)
            p.setOnPreparedListener { it.start() }
            p.setOnCompletionListener { close(); completed() }
            p.setOnErrorListener { _, _, _ -> close(); failed(); true }
            p.prepareAsync()
        } catch (_: Exception) { close(); failed() }
    }

    fun close() {
        try { player?.release() } catch (_: Exception) { }
        player = null
        audioFile?.delete()
        audioFile = null
    }
}
