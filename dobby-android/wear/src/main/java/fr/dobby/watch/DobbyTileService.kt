package fr.dobby.watch

import android.content.ComponentName
import android.content.Context
import androidx.wear.tiles.TileService
import androidx.wear.tiles.RequestBuilders
import androidx.wear.tiles.TileBuilders
import androidx.wear.protolayout.ActionBuilders
import androidx.wear.protolayout.ColorBuilders
import androidx.wear.protolayout.DimensionBuilders
import androidx.wear.protolayout.LayoutElementBuilders
import androidx.wear.protolayout.ModifiersBuilders
import androidx.wear.protolayout.ResourceBuilders
import androidx.wear.protolayout.TimelineBuilders
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

internal fun tileListenAction(context: Context) = ActionBuilders.launchAction(ComponentName(context, TileListenActivity::class.java))

class DobbyTileService : TileService() {
    override fun onTileRequest(requestParams: RequestBuilders.TileRequest): ListenableFuture<TileBuilders.Tile> {
        val prefs = getSharedPreferences("dobby_tile", MODE_PRIVATE)
        val received = prefs.getLong("received", 0)
        val recent = received > 0 && System.currentTimeMillis() - received in 0..900000
        val status = if (recent) "Données récentes" else "Connexion indisponible"
        val last = if (received > 0) prefs.getString("last", "inconnue") ?: "inconnue" else "inconnue"
        val pending = prefs.getInt("pending", 0)
        fun text(value: String, size: Float, color: Int) = LayoutElementBuilders.Text.Builder().setText(value)
            .setFontStyle(LayoutElementBuilders.FontStyle.Builder().setSize(DimensionBuilders.sp(size)).setColor(ColorBuilders.argb(color)).build()).build()
        val action = tileListenAction(this)
        val click = ModifiersBuilders.Clickable.Builder().setId("listen").setOnClick(action).build()
        val button = LayoutElementBuilders.Box.Builder().setWidth(DimensionBuilders.dp(110f)).setHeight(DimensionBuilders.dp(48f))
            .setModifiers(ModifiersBuilders.Modifiers.Builder().setClickable(click).setBackground(ModifiersBuilders.Background.Builder().setColor(ColorBuilders.argb(0xff083552.toInt())).setCorner(ModifiersBuilders.Corner.Builder().setRadius(DimensionBuilders.dp(24f)).build()).build()).build())
            .addContent(text("◉  Parler", 16f, 0xff8deaff.toInt())).build()
        val column = LayoutElementBuilders.Column.Builder().addContent(text("✦ DOBBY", 19f, 0xff55dfff.toInt()))
            .addContent(text(status, 10f, 0xffb0c7d1.toInt())).addContent(button)
            .addContent(text("Mission : $last", 10f, 0xffdceff4.toInt()))
            .addContent(text("À approuver : $pending", 10f, 0xffdceff4.toInt())).build()
        val layout = LayoutElementBuilders.Layout.Builder().setRoot(column).build()
        val timeline = TimelineBuilders.Timeline.Builder().addTimelineEntry(TimelineBuilders.TimelineEntry.Builder().setLayout(layout).build()).build()
        return Futures.immediateFuture(TileBuilders.Tile.Builder().setResourcesVersion("1").setTileTimeline(timeline).setFreshnessIntervalMillis(900000).build())
    }

    override fun onTileResourcesRequest(requestParams: RequestBuilders.ResourcesRequest): ListenableFuture<ResourceBuilders.Resources> =
        Futures.immediateFuture(ResourceBuilders.Resources.Builder().setVersion("1").build())
}
