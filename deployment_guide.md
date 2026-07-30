# Deployment Guide — Hosting the Ops Console on GCP Free Tier

This step-by-step guide explains how to create a **100% Free Forever** virtual server on Google Cloud Platform (GCP), deploy the codebase, and run the Ops Console website.

---

## Step 1: Create Your Free GCP Virtual Machine (VM)

1. Go to the [Google Cloud Console](https://console.cloud.google.com/). Sign in or create a free account (Google gives $300 free trial credits).
2. Create or select a project.
3. In the left sidebar, navigate to **Compute Engine** ➔ **VM Instances**.
4. Click **Create Instance** at the top.
5. Configure the instance with the following settings to keep it **100% Free**:
   * **Name**: `stats-agent`
   * **Region**: Select **`us-central1` (Iowa)**, **`us-east1` (South Carolina)**, or **`us-west1` (Oregon)**. *(GCP Always Free tier only covers these three regions)*.
   * **Machine configuration**: Select **General-purpose** ➔ **E2** series.
   * **Machine type**: Select **`e2-micro`** (2 vCPU, 1 GB memory). *(This machine is free forever)*.
   * **Boot disk**: Click **Change**:
     * **Operating System**: select **Ubuntu**.
     * **Version**: select **Ubuntu 22.04 LTS** (or newer).
     * **Boot disk type**: select **Standard persistent disk**.
     * **Size (GB)**: enter **`30`**. *(GCP Always Free allows up to 30 GB of storage)*.
     * Click **Select**.
   * **Firewall**: Check both **Allow HTTP traffic** and **Allow HTTPS traffic**.
6. Click **Create** at the bottom. Wait 1–2 minutes for the green checkmark next to your instance.

---

## Step 2: Open Port 8000 in the GCP Firewall

By default, GCP blocks all external ports. Since our server runs on port `8000`, we need to allow traffic on it.

1. Search for **Firewall** in the top Google Cloud search bar and click **Firewall (VPC Network)**.
2. Click **Create Firewall Rule** at the top.
3. Configure the rule:
   * **Name**: `allow-ops-console`
   * **Targets**: select **All instances in the network**.
   * **Source IPv4 ranges**: enter **`0.0.0.0/0`**. *(This allows anyone to access the site. For extra security, you can type your company's IP range instead)*.
   * **Protocols and ports**: Check **Specified protocols and ports**, check **TCP**, and type **`8000`** in the text box.
4. Click **Create**.

---

## Step 3: Connect to the Server

1. Go back to **Compute Engine** ➔ **VM Instances**.
2. Locate your `stats-agent` instance.
3. In the "Connect" column, click the **SSH** button.
4. This will open a secure terminal window directly in your web browser. You are now logged into the cloud server!

---

## Step 4: Clone and Setup the Project

In the SSH browser window that opened, run the following commands one-by-one:

1. **Install Git**:
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   ```

2. **Clone your repository**:
   ```bash
   git clone https://github.com/dugadnaman/Stats-Agent.git
   ```

3. **Navigate to the folder**:
   ```bash
   cd Stats-Agent
   ```

---

## Step 5: Copy Your Config Files (`.env` and `service_account.json`)

Since these configuration files are ignored by git, we need to create them manually on the server.

1. **Create the `.env` file**:
   * Run:
     ```bash
     nano .env
     ```
   * Paste your local `.env` contents (you can copy them from your local computer and right-click to paste in the SSH window).
   * Save and exit: press `Ctrl+O` then `Enter` (to save), then `Ctrl+X` (to exit).

2. **Create the `service_account.json` file**:
   * Run:
     ```bash
     nano service_account.json
     ```
   * Copy the full content of your local `service_account.json` file, paste it into the editor.
   * Save and exit: press `Ctrl+O` then `Enter`, then `Ctrl+X`.

---

## Step 6: Run Setup and Launch the Server

1. **Run the installation script**:
   ```bash
   bash setup_server.sh
   ```
   *(This will automatically install Python, Pip, Chromium, Playwright, and setup the Xvfb virtual screen. This step takes 2–3 minutes).*

2. **Start the Virtual Screen and Uvicorn Server**:
   Run these three commands to start the virtual screen and launch the web server in the background:
   ```bash
   Xvfb :99 -screen 0 1280x1024x24 &
   export DISPLAY=:99
   nohup ./.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
   ```

---

## Step 7: Access the Console

1. Find the **External IP** address of your instance in the **Compute Engine ➔ VM Instances** page.
2. In your browser on any device, navigate to:
   ```
   http://<your-vm-external-ip>:8000
   ```
3. The site is live! Anyone in your company can now visit this link, select multiple verticals, select a date, and click **▶ Run agent** to automate the stats sync.
