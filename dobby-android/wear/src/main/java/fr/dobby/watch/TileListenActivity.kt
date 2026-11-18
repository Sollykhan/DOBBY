package fr.dobby.watch

import android.app.Activity
import android.content.Intent
import android.os.Bundle

const val EXTRA_START_LISTENING = "fr.dobby.watch.START_LISTENING"
internal fun consumeListenRequest(intent: Intent?): Boolean {
    // Wear OS can retain a previously rendered tile after an APK update.
    val requested = intent?.getBooleanExtra(EXTRA_START_LISTENING, false) == true || intent?.getBooleanExtra("listen", false) == true
    intent?.removeExtra(EXTRA_START_LISTENING)
    intent?.removeExtra("listen")
    return requested
}

class TileListenActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) {
            startActivity(Intent(this, MainActivity::class.java).putExtra(EXTRA_START_LISTENING, true)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
        }
        finish()
    }
}
