# Client camera access and HTTPS

The camera belongs to the computer running the browser, not the server. Camera permission is requested from the vision laboratory (`/#vision`). Audio is not requested.

## Configure local HTTPS

Set these values in `.env` before starting:

```dotenv
POSTURE_TLS_HOST=localhost
POSTURE_TLS_EXTRA_HOST=127.0.0.1
POSTURE_TLS_PORT=8443
```

These values suit a browser on the server itself. For remote clients, use the DNS name/IP actually used to reach your server. Apply changes with `./launch_docker up`.

- HTTPS: `https://<your-server-host>:8443/#vision`.
- HTTP: `http://<your-server-host>:8080/`; uploads work here, but a remote camera needs a secure context.
- Caddy issues/renews certificates through a local CA; no public domain or Internet exposure is needed.
- Each client trusts the public root once. The private key stays in the Caddy data volume.

Use `POSTURE_TLS_HOST` as the primary address; clients without SNI receive its certificate. The root remains stable while `caddy_data` is preserved. A future public-domain deployment can configure Caddy with a publicly trusted CA.

## Obtain and verify the public root

As an administrator, open the vision laboratory camera panel over HTTP and download `POSTURE-root.crt`. Development authentication mode also permits anonymous access.

The exported root is at `.runtime/posture-root.crt`, relative to the repository root. Export it again with:

```bash
./launch_docker certificate
```

Compare the printed SHA-256 fingerprint against the downloaded file before trusting it:

```bash
openssl x509 -in POSTURE-root.crt -noout -fingerprint -sha256
```

### Windows: Chrome / Edge

1. Open the file and choose **Install Certificate**.
2. Select **Current User** and **Trusted Root Certification Authorities**.
3. Complete the import and restart the browser.
4. Visit the configured HTTPS address and allow camera access.

Use `certmgr.msc` to manage/remove the root. Firefox may require its own import.

### macOS

Import the certificate in **Keychain Access**. Open its **Trust** section, select **Always Trust** for this root, restart the browser and open HTTPS.

### Linux

Import the root into the browser's certificate authorities. Firefox provides **Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import**; enable website identification trust. Menus vary by version.

On Debian/Ubuntu, additionally install it in the system trust store using these standard OS paths, independent of the repository location:

```bash
sudo cp POSTURE-root.crt /usr/local/share/ca-certificates/posture-root.crt
sudo update-ca-certificates
```

Restart the browser; a separate browser import may still be required. Bypassing a TLS warning does not install trust. Camera capture should use a page without certificate errors.

## Alternative: SSH tunnel and localhost

```bash
ssh -N -L 18080:127.0.0.1:8080 <ssh-user>@<your-server-host>
```

Keep the terminal open and visit `http://localhost:18080/#vision` on the client. Browsers consider localhost a secure context; remote traffic uses SSH.

References: [browser camera requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [Caddy local HTTPS](https://caddyserver.com/docs/automatic-https#local-https).
