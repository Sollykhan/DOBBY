package fr.dobby.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URL
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection

class SetupRequired : IllegalStateException("Première configuration requise.")

data class Mission(val id: String, val state: String, val mode: String, val calls: Int, val turns: Int)

object Endpoint {
    const val FIRST_USE_CODE = "000000"
    fun validPin(value: String): Boolean = Regex("^[0-9]{6}$").matches(value)
    fun validNewPin(value: String): Boolean = validPin(value) && value != FIRST_USE_CODE
    fun canonical(value: String): String {
        val url = URL(value.trim().trimEnd('/'))
        require(url.protocol == "https" && url.host.lowercase().endsWith(".ts.net")) { "Une adresse HTTPS Tailscale .ts.net est requise." }
        require(url.userInfo == null && url.port in listOf(-1, 443, 8443) && url.path.isEmpty() && url.query == null && url.ref == null) { "Adresse Tailscale invalide." }
        val port = if (url.port == 8443) ":8443" else ""
        return "https://${url.host.lowercase()}$port"
    }
    fun missionId(value: String): String {
        require(Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$").matches(value))
        return value
    }
}

/** Only a short-lived server session is encrypted; the access code is never stored. */
class Vault(context: Context) {
    private val prefs = context.getSharedPreferences("dobby_secure", Context.MODE_PRIVATE)
    private val alias = "dobby_session_v1"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }
    fun save(origin: String, cookie: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.doFinal(JSONObject().put("origin", origin).put("cookie", cookie).toString().toByteArray())
        prefs.edit().putString("session", Base64.encodeToString(cipher.iv + encrypted, Base64.NO_WRAP)).apply()
    }
    fun load(): Pair<String, String>? {
        return try {
            val bytes = Base64.decode(prefs.getString("session", null) ?: return null, Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
            val obj = JSONObject(String(cipher.doFinal(bytes.copyOfRange(12, bytes.size))))
            Endpoint.canonical(obj.getString("origin")) to obj.getString("cookie")
        } catch (_: Exception) { null }
    }
    fun clear() { prefs.edit().clear().apply() }
}

class Backend(private val origin: String, private var cookie: String? = null) {
    private suspend fun request(path: String, body: JSONObject? = null): Pair<JSONObject, String?> = withContext(Dispatchers.IO) {
        val base = Endpoint.canonical(origin)
        val connection = (URL(base + path).openConnection() as HttpsURLConnection).apply {
            connectTimeout = 10000; readTimeout = 10000; instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            cookie?.let { setRequestProperty("Cookie", it) }
            if (body != null) { requestMethod = "POST"; doOutput = true; setRequestProperty("Content-Type", "application/json"); setRequestProperty("Origin", base) }
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray()) }
            val status = connection.responseCode
            if (status == 428) throw SetupRequired()
            if (status !in 200..299) throw IllegalStateException(if (status == 401 || status == 403) "Session expirée ou accès refusé." else "Serveur indisponible ($status).")
            val bytes = connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (output.size() <= 65536) {
                    val n = input.read(buffer, 0, minOf(buffer.size, 65537 - output.size()))
                    if (n < 0) break
                    output.write(buffer, 0, n)
                }
                output.toByteArray()
            }
            require(bytes.size <= 65536) { "Réponse trop volumineuse." }
            JSONObject(String(bytes)) to connection.getHeaderField("Set-Cookie")
        } finally { connection.disconnect() }
    }
    suspend fun login(code: String): String {
        val (_, header) = request("/api/login", JSONObject().put("password", code))
        return captureSession(header)
    }
    suspend fun setup(pin: String, confirmation: String): String {
        require(Endpoint.validNewPin(pin) && pin == confirmation)
        val (_, header) = request("/api/setup", JSONObject().put("bootstrap", Endpoint.FIRST_USE_CODE).put("pin", pin).put("confirmation", confirmation))
        return captureSession(header)
    }
    private fun captureSession(header: String?): String {
        val session = header?.substringBefore(';') ?: error("Session absente.")
        require(Regex("^dobby_session=[A-Za-z0-9_-]{20,128}$").matches(session))
        cookie = session
        return session
    }
    suspend fun missions(): List<Mission> {
        val arr = request("/api/missions").first.getJSONArray("missions")
        return (0 until arr.length()).map { i -> arr.getJSONObject(i).let { Mission(it.getString("id"), it.getString("state"), it.getString("mode"), it.optInt("api_calls"), it.optInt("turns")) } }
    }
    suspend fun liveEnabled(): Boolean = request("/api/session").first.optBoolean("live_enabled", false)
    suspend fun calendarPlan(question: String): JSONObject = request("/api/calendar/plan", JSONObject().put("question", question)).first
    suspend fun speech(text: String, language: String = "fr"): ByteArray = withContext(Dispatchers.IO) {
        require(text.isNotBlank() && text.length <= 500 && language in setOf("fr", "en"))
        val base = Endpoint.canonical(origin)
        val conn = (URL(base + "/api/speech").openConnection() as HttpsURLConnection).apply {
            connectTimeout = 10000; readTimeout = 35000; instanceFollowRedirects = false
            requestMethod = "POST"; doOutput = true
            setRequestProperty("Content-Type", "application/json"); setRequestProperty("Origin", base)
            cookie?.let { setRequestProperty("Cookie", it) }
        }
        try {
            conn.outputStream.use { it.write(JSONObject().put("text", text).put("language", language).toString().toByteArray(Charsets.UTF_8)) }
            check(conn.responseCode == 200 && conn.contentType?.startsWith("audio/wav") == true)
            conn.inputStream.use { input ->
                val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                while (true) { val n = input.read(buffer); if (n < 0) break; require(out.size() + n <= 3 * 1024 * 1024); out.write(buffer, 0, n) }
                out.toByteArray().also { require(it.size >= 12 && String(it, 0, 4, Charsets.US_ASCII) == "RIFF" && String(it, 8, 4, Charsets.US_ASCII) == "WAVE") }
            }
        } finally { conn.disconnect() }
    }
    suspend fun voice(question: String, events: org.json.JSONArray? = null): String {
        require(question.isNotBlank() && question.length <= 500)
        val body = JSONObject().put("question", question)
        if (events != null) body.put("android_events", events)
        return request("/api/voice", body).first.getString("reply").also { require(it.length <= 500) }
    }
    suspend fun detail(id: String) = request("/api/missions/${Endpoint.missionId(id)}").first
    suspend fun createSimulation(): String = request("/api/missions", JSONObject().put("mode", "simulation")).first.getString("id")
    suspend fun createLive(): String = request("/api/missions", JSONObject().put("mode", "live").put("billing_confirmed", true)).first.getString("id")
    suspend fun approve(id: String) { request("/api/missions/${Endpoint.missionId(id)}/approve", JSONObject().put("approve", true)) }
}
