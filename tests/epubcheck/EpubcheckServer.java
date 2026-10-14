// Runs epubcheck on many EPUBs in one JVM, so the test suite starts the JVM once per pytest
// process instead of once per EPUB (tests/conftest.py, TST-R19).
//
// Run with Java's source-file launcher: java -cp epubcheck.jar EpubcheckServer.java
// Protocol: each line on stdin is the path of one EPUB. For each, one line goes to stdout:
// epubcheck's exit code, a space, and everything epubcheck printed, Base64-encoded.

import com.adobe.epubcheck.tool.EpubChecker;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

public class EpubcheckServer {
    public static void main(String[] args) throws IOException {
        PrintStream reply = System.out;
        PrintStream log = System.err;
        BufferedReader requests =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String path;
        while ((path = requests.readLine()) != null) {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            PrintStream capture = new PrintStream(buffer, true, StandardCharsets.UTF_8);
            System.setOut(capture);
            System.setErr(capture);
            int code;
            try {
                code = new EpubChecker().run(new String[] {path, "--quiet"});
            } catch (Throwable failure) {
                failure.printStackTrace(capture);
                code = -1;
            } finally {
                System.setOut(reply);
                System.setErr(log);
            }
            capture.flush();
            reply.println(code + " " + Base64.getEncoder().encodeToString(buffer.toByteArray()));
            reply.flush();
        }
    }
}
