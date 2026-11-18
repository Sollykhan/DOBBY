package fr.dobby.watch

import android.content.Intent
import android.content.Context
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class TileListenTest {
    @Test fun tileOpensTrampolineWhichForwardsListenRequest() {
        val context: Context = RuntimeEnvironment.getApplication()
        val target = tileListenAction(context).androidActivity!!
        assertEquals(TileListenActivity::class.java.name, target.className)
        val trampoline = Robolectric.buildActivity(TileListenActivity::class.java).create().get()
        val forwarded = shadowOf(trampoline).nextStartedActivity
        assertEquals(MainActivity::class.java.name, forwarded.component!!.className)
        assertTrue(forwarded.getBooleanExtra(EXTRA_START_LISTENING, false))
    }

    @Test fun requestIsConsumedOnceAndNormalLaunchDoesNotListen() {
        val intent = Intent().putExtra(EXTRA_START_LISTENING, true)
        assertTrue(consumeListenRequest(intent))
        assertFalse(consumeListenRequest(intent))
        assertFalse(consumeListenRequest(Intent()))
        val cachedTile = Intent().putExtra("listen", true)
        assertTrue(consumeListenRequest(cachedTile))
        assertFalse(consumeListenRequest(cachedTile))
    }

    @Test fun activityConsumesOnCreateAndOnNewIntent() {
        val context: Context = RuntimeEnvironment.getApplication()
        val launch = Intent(context, MainActivity::class.java).putExtra(EXTRA_START_LISTENING, true)
        val controller = Robolectric.buildActivity(MainActivity::class.java, launch).create()
        assertFalse(controller.get().intent.hasExtra(EXTRA_START_LISTENING))
        val next = Intent(context, MainActivity::class.java).putExtra(EXTRA_START_LISTENING, true)
        controller.newIntent(next)
        assertFalse(next.hasExtra(EXTRA_START_LISTENING))
        controller.destroy()
    }
}
