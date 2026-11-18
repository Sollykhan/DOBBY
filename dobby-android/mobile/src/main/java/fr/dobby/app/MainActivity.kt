package fr.dobby.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Bundle
import android.speech.RecognizerIntent
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

private val Ink = Color(0xFF101510)
private val Moss = Color(0xFFC8E693)
private val Cream = Color(0xFFF3F1DD)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val missionId = intent.getStringExtra("mission_id")
        val work = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork("dobby-sync", ExistingPeriodicWorkPolicy.KEEP, work)
        setContent { MaterialTheme(colorScheme = darkColorScheme(primary = Moss, background = Ink, surface = Color(0xFF1A2119), onSurface = Cream)) { Dobby(this, missionId) } }
    }
}

private fun networkDescription(context: Context): String {
    val cm = context.getSystemService(ConnectivityManager::class.java)
    val capabilities = cm.getNetworkCapabilities(cm.activeNetwork)
    val vpn = capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
    val tailscaleInstalled = try { context.packageManager.getPackageInfo("com.tailscale.ipn", 0); true } catch (_: PackageManager.NameNotFoundException) { false }
    return when {
        vpn && tailscaleInstalled -> "VPN actif · Tailscale installé (connexion à confirmer)"
        vpn -> "VPN actif · Tailscale non détecté"
        tailscaleInstalled -> "Tailscale installé · aucun VPN actif détecté"
        else -> "Tailscale non détecté · vérifiez votre connexion privée"
    }
}

@Composable
private fun Dobby(context: Context, notificationMission: String?) {
    val vault = remember { Vault(context) }
    val initial = remember { vault.load() }
    var origin by remember { mutableStateOf(initial?.first ?: "") }
    var session by remember { mutableStateOf(initial?.second) }
    var accessCode by remember { mutableStateOf("") }
    var setupRequired by remember { mutableStateOf(false) }
    var newPin by remember { mutableStateOf("") }
    var confirmPin by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("Connexion au serveur non vérifiée") }
    var error by remember { mutableStateOf("") }
    var missions by remember { mutableStateOf<List<Mission>>(emptyList()) }
    var selected by remember { mutableStateOf(notificationMission) }
    var detail by remember { mutableStateOf("") }
    var liveEnabled by remember { mutableStateOf(false) }
    var confirmApproval by remember { mutableStateOf(false) }
    var confirmLive by remember { mutableStateOf(false) }
    var dictated by remember { mutableStateOf("") }
    var voiceReply by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val speech = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) dictated = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty()
    }
    suspend fun refresh() {
        val token = session ?: return
        try {
            val client = Backend(Endpoint.canonical(origin), token)
            missions = client.missions()
            liveEnabled = client.liveEnabled()
            selected?.let { id ->
                val data = client.detail(id)
                val messages = data.getJSONArray("messages")
                detail = (0 until messages.length()).joinToString("\n\n") { i ->
                    val m = messages.getJSONObject(i); val body = m.getJSONObject("body")
                    (if (m.getString("role") == "architect") "ARCHITECTE" else "CODEX") + "\n" + body.optString("summary")
                }
            }
            status = "Serveur DOBBY joignable"
            try { WearSync.publish(context, missions) } catch (_: Exception) { }
            error = ""
        } catch (e: Exception) {
            status = "Serveur indisponible ou session expirée"
            if (e.message?.contains("Session expirée") == true) { vault.clear(); session = null }
        }
    }
    LaunchedEffect(session) {
        if (session != null && android.os.Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        while (session != null) { refresh(); delay(20000) }
    }
    Column(Modifier.fillMaxSize().background(Ink).padding(20.dp)) {
        Text("✦  DOBBY", color = Moss, fontSize = 24.sp, fontFamily = FontFamily.Serif)
        Spacer(Modifier.height(6.dp))
        Text(networkDescription(context), color = Color(0xFFA8B8A0), fontSize = 12.sp)
        Text(status, color = Color(0xFFA8B8A0), fontSize = 12.sp)
        Spacer(Modifier.height(18.dp))
        if (session == null) {
            Text("Votre espace personnel", fontFamily = FontFamily.Serif, fontSize = 28.sp)
            OutlinedTextField(origin, { origin = it }, label = { Text("Adresse HTTPS Tailscale") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            if (!setupRequired) {
                Text("Première configuration : saisissez 000000. DOBBY vous demandera de choisir votre PIN personnel.", color = Color(0xFFA8B8A0), fontSize = 13.sp)
                OutlinedTextField(accessCode, { accessCode = it.filter { c -> c in '0'..'9' }.take(6) }, label = { Text("PIN à 6 chiffres") }, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth(), singleLine = true)
                Button(enabled = Endpoint.validPin(accessCode), onClick = { scope.launch {
                    try { val url = Endpoint.canonical(origin); val token = Backend(url).login(accessCode); vault.save(url, token); origin = url; session = token; accessCode = ""; error = "" }
                    catch (_: SetupRequired) { accessCode = ""; setupRequired = true; error = "" }
                    catch (_: Exception) { accessCode = ""; error = "Connexion impossible. Vérifiez le code, Tailscale et l'adresse." }
                } }, modifier = Modifier.fillMaxWidth().padding(top = 14.dp)) { Text("Continuer") }
            } else {
                Text("Choisissez un nouveau PIN DOBBY à 6 chiffres.", color = Color(0xFFA8B8A0), fontSize = 13.sp)
                OutlinedTextField(newPin, { newPin = it.filter { c -> c in '0'..'9' }.take(6) }, label = { Text("Nouveau PIN") }, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth(), singleLine = true)
                OutlinedTextField(confirmPin, { confirmPin = it.filter { c -> c in '0'..'9' }.take(6) }, label = { Text("Confirmer le nouveau PIN") }, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth(), singleLine = true)
                Button(enabled = Endpoint.validNewPin(newPin) && newPin == confirmPin, onClick = { scope.launch {
                    try { val url = Endpoint.canonical(origin); val token = Backend(url).setup(newPin, confirmPin); vault.save(url, token); origin = url; session = token; newPin = ""; confirmPin = ""; setupRequired = false; error = "" }
                    catch (_: Exception) { newPin = ""; confirmPin = ""; error = "Configuration refusée ou déjà effectuée. Vérifiez Tailscale puis recommencez." }
                } }, modifier = Modifier.fillMaxWidth().padding(top = 14.dp)) { Text("Enregistrer et synchroniser") }
            }
        } else {
            TextButton(onClick = { context.startActivity(Intent(context, CalendarSettingsActivity::class.java)) }) { Text("Calendriers du téléphone") }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { scope.launch { try { selected = Backend(origin, session).createSimulation(); refresh() } catch (_: Exception) { error = "Création impossible." } } }) { Text("+ Simulation") }
                if (liveEnabled) OutlinedButton(onClick = { confirmLive = true }) { Text("Mission réelle") }
                TextButton(onClick = { vault.clear(); session = null; missions = emptyList(); selected = null }) { Text("Quitter") }
            }
            Text("Analyse en lecture seule · 3 cycles max · 6 appels API max", fontSize = 11.sp, color = Color(0xFFA8B8A0))
            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                val wide = maxWidth >= 600.dp
                if (wide) {
                    Row(Modifier.fillMaxSize()) {
                        MissionList(missions, Modifier.weight(1f)) { selected = it; scope.launch { refresh() } }
                        DetailPane(selected, detail, missions, Modifier.weight(1f)) { confirmApproval = true }
                    }
                } else {
                    Column(Modifier.fillMaxSize()) {
                        MissionList(missions, Modifier.weight(1f)) { selected = it; scope.launch { refresh() } }
                        DetailPane(selected, detail, missions, Modifier.weight(1f)) { confirmApproval = true }
                    }
                }
            }
            TextButton(onClick = {
                try { speech.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)) }
                catch (_: Exception) { error = "Dictée non disponible sur cet appareil." }
            }) { Text("Dicter une note (sans action)") }
            if (dictated.isNotBlank()) {
                Text(dictated, fontSize = 12.sp, maxLines = 2)
                TextButton(onClick = { scope.launch { try { voiceReply = VoiceWithCalendars.ask(context, Backend(origin, session), dictated); error = "" } catch (_: Exception) { error = "Calendrier ou connexion indisponible ; vérifiez les autorisations et la sélection." } } }) { Text("Demander à DOBBY") }
                if (voiceReply.isNotBlank()) Text(voiceReply, fontSize = 12.sp)
            }
        }
        if (error.isNotEmpty()) Text(error, color = Color(0xFFFFB4AB), fontSize = 12.sp)
    }
    if (confirmApproval) AlertDialog(onDismissRequest = { confirmApproval = false }, title = { Text("Confirmer l’approbation") },
        text = { Text("Autoriser cette étape après examen de la proposition ?") },
        confirmButton = { TextButton(onClick = { confirmApproval = false; scope.launch { try { selected?.let { Backend(origin, session).approve(it) }; refresh() } catch (_: Exception) { error = "Approbation impossible." } } }) { Text("Approuver") } },
        dismissButton = { TextButton(onClick = { confirmApproval = false }) { Text("Annuler") } })
    if (confirmLive) AlertDialog(onDismissRequest = { confirmLive = false }, title = { Text("Mission réelle et facturation") },
        text = { Text("Cette mission utilise l’API OpenAI facturable. Confirmez que les paramètres de facturation sont vérifiés. Codex demandera une approbation séparée.") },
        confirmButton = { TextButton(onClick = { confirmLive = false; scope.launch { try { selected = Backend(origin, session).createLive(); refresh() } catch (_: Exception) { error = "Mission réelle indisponible." } } }) { Text("Confirmer") } },
        dismissButton = { TextButton(onClick = { confirmLive = false }) { Text("Annuler") } })
}

@Composable private fun MissionList(missions: List<Mission>, modifier: Modifier, select: (String) -> Unit) {
    LazyColumn(modifier.padding(top = 12.dp)) {
        item { Text("Vos missions", fontFamily = FontFamily.Serif, fontSize = 24.sp); Spacer(Modifier.height(8.dp)) }
        if (missions.isEmpty()) item { Text("Aucune mission pour le moment.", color = Color(0xFFA8B8A0)) }
        items(missions) { mission ->
            Card(onClick = { select(mission.id) }, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(14.dp)) { Text("Analyse du dépôt témoin"); Text("${mission.state} · ${mission.mode} · ${mission.calls}/6 API", fontSize = 12.sp, color = Moss) }
            }
        }
    }
}

@Composable private fun DetailPane(selected: String?, detail: String, missions: List<Mission>, modifier: Modifier, approve: () -> Unit) {
    Column(modifier.fillMaxWidth().padding(top = 12.dp)) {
        Text("Échanges", fontFamily = FontFamily.Serif, fontSize = 24.sp)
        if (selected == null) Text("Sélectionnez une mission.", color = Color(0xFFA8B8A0))
        else {
            LazyColumn(Modifier.weight(1f)) { item { Text(detail.ifBlank { "Chargement…" }, fontSize = 14.sp, modifier = Modifier.padding(vertical = 12.dp)) } }
            if (missions.any { it.id == selected && it.state == "awaiting_approval" }) Button(onClick = approve) { Text("Examiner et approuver") }
        }
    }
}
