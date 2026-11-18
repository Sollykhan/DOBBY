package fr.dobby.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EndpointTest {
    @Test fun pinRequiresSixAsciiDigits() {
        assertTrue(Endpoint.validPin("258036"))
        assertTrue(Endpoint.validNewPin("258036"))
        assertFalse(Endpoint.validNewPin(Endpoint.FIRST_USE_CODE))
        listOf("12345", "1234567", "１２３４５６", "abc123").forEach { assertFalse(Endpoint.validPin(it)) }
    }
    @Test fun acceptsOnlyHttpsTailnetHost() {
        assertEquals("https://machine.tail123.ts.net", Endpoint.canonical("https://machine.tail123.ts.net/"))
        assertEquals("https://machine.tail123.ts.net:8443", Endpoint.canonical("https://machine.tail123.ts.net:8443/"))
        assertEquals("https://machine.tail123.ts.net", Endpoint.canonical("https://machine.tail123.ts.net:443"))
        listOf("http://machine.tail123.ts.net", "https://example.com", "https://machine.tail123.ts.net:1234", "https://machine.tail123.ts.net/path", "https://user:pass@machine.tail123.ts.net").forEach {
            try { Endpoint.canonical(it); throw AssertionError("unsafe address accepted") } catch (_: IllegalArgumentException) { }
        }
    }
    @Test fun rejectsCommandsAndPathsAsIdentifiers() {
        val id = "12345678-1234-1234-1234-123456789abc"
        assertEquals(id, Endpoint.missionId(id))
        listOf("../../etc", "id;whoami", "wrong").forEach {
            try { Endpoint.missionId(it); throw AssertionError("unsafe id accepted") } catch (_: IllegalArgumentException) { }
        }
    }
}
