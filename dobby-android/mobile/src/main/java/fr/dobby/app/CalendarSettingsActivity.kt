package fr.dobby.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.CalendarContract
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit
import android.content.ContentUris
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneOffset
import java.time.ZoneId

data class LocalCalendar(val id: Long, val name: String, val occurrences: Int)

object LocalCalendarReader {
    fun selectedEvents(context: Context, start: String, end: String): JSONArray {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) throw SecurityException()
        val ids = context.getSharedPreferences("dobby_calendars", Context.MODE_PRIVATE).getStringSet("selected", emptySet())?.mapNotNull { it.toLongOrNull() } ?: emptyList()
        if (ids.isEmpty()) return JSONArray()
        require(ids.size <= 30)
        val begin = Instant.parse(start).toEpochMilli(); val finish = Instant.parse(end).toEpochMilli()
        require(finish > begin && finish - begin <= TimeUnit.DAYS.toMillis(32))
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also { ContentUris.appendId(it, begin); ContentUris.appendId(it, finish) }.build()
        val columns = arrayOf(CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN, CalendarContract.Instances.END, CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.AVAILABILITY)
        val selection = CalendarContract.Instances.CALENDAR_ID + " IN (" + ids.joinToString(",") { "?" } + ")"
        val result = JSONArray()
        context.contentResolver.query(uri, columns, selection, ids.map { it.toString() }.toTypedArray(), CalendarContract.Instances.BEGIN + " ASC")?.use { c ->
            while (c.moveToNext()) {
                if (result.length() >= 20) error("Trop d'événements pour une réponse complète")
                val allDay = c.getInt(3) != 0
                fun time(ms: Long): String = if (allDay) Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate().atStartOfDay(ZoneId.of("Europe/Paris")).toOffsetDateTime().toString() else Instant.ofEpochMilli(ms).toString()
                result.put(JSONObject().put("title", (c.getString(0) ?: "(sans titre)").take(120)).put("start", time(c.getLong(1))).put("end", time(c.getLong(2))).put("all_day", allDay).put("busy", c.getInt(4) != CalendarContract.Instances.AVAILABILITY_FREE))
            }
        } ?: error("Occurrences indisponibles")
        return result
    }
    fun calendars(context: Context): List<LocalCalendar> {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) throw SecurityException()
        val names = linkedMapOf<Long, String>()
        val resolver = context.contentResolver
        resolver.query(CalendarContract.Calendars.CONTENT_URI, arrayOf(CalendarContract.Calendars._ID, CalendarContract.Calendars.CALENDAR_DISPLAY_NAME), null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) names[cursor.getLong(0)] = cursor.getString(1) ?: "Calendrier sans nom"
        } ?: error("Calendriers indisponibles")
        val counts = mutableMapOf<Long, Int>()
        val now = System.currentTimeMillis(); val range = TimeUnit.DAYS.toMillis(365)
        CalendarContract.Instances.query(resolver, arrayOf(CalendarContract.Instances.CALENDAR_ID), now - range, now + range)?.use { cursor ->
            while (cursor.moveToNext()) { val id = cursor.getLong(0); counts[id] = (counts[id] ?: 0) + 1 }
        } ?: error("Occurrences indisponibles")
        return names.map { (id, name) -> LocalCalendar(id, name, counts[id] ?: 0) }
    }
}

class CalendarSettingsActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme(colorScheme = darkColorScheme()) { CalendarSettings(this) } }
    }
}

@Composable private fun CalendarSettings(context: Context) {
    var calendars by remember { mutableStateOf<List<LocalCalendar>>(emptyList()) }
    var message by remember { mutableStateOf("La lecture reste sur le téléphone pendant ce diagnostic.") }
    var selected by remember { mutableStateOf(context.getSharedPreferences("dobby_calendars", Context.MODE_PRIVATE).getStringSet("selected", emptySet())?.toSet() ?: emptySet()) }
    val scope = rememberCoroutineScope()
    fun load() { scope.launch {
        try { calendars = withContext(Dispatchers.IO) { LocalCalendarReader.calendars(context) }; message = "Sélectionne les calendriers autorisés. Les nombres couvrent un an avant et après aujourd’hui." }
        catch (_: SecurityException) { message = "Permission calendrier refusée." }
        catch (_: Exception) { message = "Calendriers ou occurrences indisponibles sur cet appareil." }
    } }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) load() else message = "Permission calendrier refusée." }
    Column(Modifier.fillMaxSize().padding(20.dp)) {
        Text("Calendriers du téléphone", style = MaterialTheme.typography.headlineSmall)
        Text(message)
        Button(onClick = { if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED) load() else permission.launch(Manifest.permission.READ_CALENDAR) }) { Text("Vérifier les calendriers") }
        LazyColumn(Modifier.weight(1f)) { items(calendars) { calendar ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) { Text(calendar.name); Text("${calendar.occurrences} occurrences accessibles", style = MaterialTheme.typography.bodySmall) }
                Checkbox(checked = calendar.id.toString() in selected, onCheckedChange = { enabled ->
                    selected = if (enabled) selected + calendar.id.toString() else selected - calendar.id.toString()
                    context.getSharedPreferences("dobby_calendars", Context.MODE_PRIVATE).edit().putStringSet("selected", selected).apply()
                })
            }
        } }
    }
}
