## Steps to setup the server for your environment

1. Make sure to add the `mcp~=1.9.4` and `pdfminer.six==20221105` packages your pyproject file.
2. Run `bench setup requirements --python` to install the required packages.
3. Configure the following parameters in the `frappe-mcp.conf` file.
        - `command`: bench execute `current_path`.mcp_start.start_mcp_server. Update the site name with your current site.
        - `directory`: Bench working directory, typically `/home/frappe/frappe-bench`.
        - `user`: The user under which the MCP server will run.
        - `autostart`: Set to `true` to start the MCP server automatically on system boot.
        - `autorestart`: Set to `true` to automatically restart the MCP server if it crashes.
        - `stdout_logfile`: Path to the log file where standard output will be logged.
        - `environment`: FRAPPE_SITE="your site name",MCP_HOST="your-host-address",MCP_PORT=your-port-number
4. Ensure that contents of `frappe-mcp.conf` file is placed in the `your-bench-path/config/supervisor.conf` file.

### Run the following commands to reset supervisord with the updated configuration

```bash
supervisorctl reread
supervisorctl update
supervisorctl restart frappe-mcp
```



---

5. Set Up n8n Integration

> Automate background workflows, integrate APIs, or orchestrate complex processes using [n8n](https://n8n.io).

**Install PM2 and n8n**

Ensure Node.js version is **20 or above**:

```bash
node -v
# Should return v20+
```

Install globally:

```bash
npm install -g pm2
npm install -g n8n
```

**Start n8n with PM2**

```bash
pm2 start n8n --name n8n
```

Enable on startup:

```bash
pm2 startup
```

> This will output a command like:
>
> ```bash
> sudo env PATH=$PATH:/home/your-user/.nvm/versions/node/v20.x.x/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u your-user --hp /home/your-user
> ```

Run that command, then save the PM2 state:

```bash
pm2 save
```


**Setup Flow**

You can use a preconfigured n8n workflow file provided in the app.

- File Location: `ampower_jive/mcp/config/n8n-config.json`
- This JSON file contains a ready-to-use n8n flow which can be **imported directly** into the n8n dashboard.

To import:

1. Open the n8n dashboard in your browser (usually http://localhost:5678).
2. Click on the menu (top right) → `Import from file`.
3. Paste the contents of `n8n-config.json` or upload the file.
4. Configure the tools as per your requirements.

In order to use the query tool, you need to set up the `query_frappe_doctypes` tool in n8n. This tool will allow you to run queries on your Frappe data.
Follow these steps:
1. Add configuration to "Jive Config" doctype, including the webhook URL and OpenAI API key.
2. Go to "Prompt" doctype and create a new prompt defining your database:
   - **Prompt Name**: `USER_DATABASE_DEFINITION`
   - **Prompt**: `Item Level A doctype contains the most selling items in the inventory...`
3. In the n8n workflow, add a new node for the `query_frappe_doctypes` tool.
   - **Tool Name**: `query_frappe_doctypes`
4. The Agent will now use this tool to run queries relevant on your Frappe data.

The Chat URL must not include the port number, it should be in the format `https://${your-host-address}/webhook/${chat-webhook-id}/chat`.
The chat must be in the embedded mode, which can be set in the Chat object on n8n dashboard.

---


### Common issues and troubleshooting
- If the MCP server does not start, check the log file specified in `stdout_logfile` for any errors.
- Ensure that the `MCP_HOST` and `MCP_PORT` are correctly set in the environment variables.
- If you encounter permission issues, ensure that the user specified in the `user` field has the necessary permissions to access the Bench working directory and log files.
- Sometimes the server might not be able to communcate with MariaDB, this can be fixed by simply restarting the some services. An easy way is to run `supervisorctl restart all`.
- n8n not persisting, Run `pm2 save` after `pm2 startup` to persist across restarts.           |
- Node version < 20, Upgrade Node.js using NVM or a system package manager. 

But if this occurs frequently, you might want to add a cron to restart all services periodically. You can follow these steps:
1. Open the crontab editor:
   ```bash
   crontab -e
   ```
2. Add the following line to restart all services every 6 hours:
        ```bash
        0 */6 * * * /usr/bin/supervisorctl restart all
        ```
3. Then run `sudo service cron restart` to apply the changes.

With a successful setup, you could see these ports exposed on your VScode port tunnels (varies with version, but are exposed otherwise if there are no issues encountered in the MCP log file):

<img width="450" height="142" alt="image" src="https://github.com/user-attachments/assets/e52f09a2-975f-4778-aaa8-ed7db2877260" />


### Testing a cURL

```bash
curl -X POST http://your-host-address:your-port/mcp/tools/list \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": "tools-list",
    "method": "tools/list",
    "params": {}
}'
```


