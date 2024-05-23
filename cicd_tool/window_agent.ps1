# Constants for server URLs
$SERVER_URL = 'http://localhost:8000/pipeline'
$REGISTER_URL = "$SERVER_URL/agents/register/"
$HEARTBEAT_URL = "$SERVER_URL/agents/receive-heartbeat/"

# Port for receiving commands
$AGENT_COMMAND_PORT = 9000

# Function to register the agent
function Register-Agent {
    param (
        [string]$HashKey
    )

    try {
        $hostname = hostname
        $ipconfig_output = & ipconfig
        $ip_address = $ipconfig_output | Where-Object { $_ -match "IPv4 Address" } | ForEach-Object { ($_ -split ":")[1].Trim() }

        if (-not $ip_address) {
            throw "Could not determine IP address"
        }

        $jsonBody = @{
            'hostname' = $hostname
            'ip_address' = $ip_address
            'hash_key' = $HashKey
            'operating_system' = 'Windows'
        } | ConvertTo-Json

        $response = Invoke-RestMethod -Uri $REGISTER_URL -Method Post -ContentType "application/json" -Body $jsonBody

        if ($response.StatusCode -eq 200) {
            Write-Host "Agent registered successfully."
        } else {
            $errorMessage = "Failed to register agent: $($response.Content)"
            Write-Host $errorMessage
            throw $errorMessage
        }
    } catch {
        Write-Host "Error during agent registration: $_"
    }
}

# Function to receive command from server
function Receive-Command {
    param (
        [string]$HashKey
    )

    try {
        # Start a listener on the specified port to receive commands
        $listener = [System.Net.Sockets.TcpListener] $AGENT_COMMAND_PORT
        $listener.Start()

        Write-Host "Waiting for commands on port $AGENT_COMMAND_PORT..."

        # Accept incoming connections and read command data
        $client = $listener.AcceptTcpClient()
        $stream = $client.GetStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $command = $reader.ReadLine()

        $listener.Stop()

        Write-Host "Received command URL: $command"

        # Extract the URL from the received command
        $urlPattern = 'POST\s+(?<url>\S+)\s+HTTP'
        $urlMatch = [regex]::Match($command, $urlPattern)
        if ($urlMatch.Success) {
            $url = $urlMatch.Groups['url'].Value
        } else {
            throw "Failed to extract URL from command: $command"
        }

        # Send a request to the extracted URL to fetch the command
        $response = Invoke-WebRequest -Uri $url -Method Get

        if ($response.StatusCode -eq 200) {
            $commandContent = $response.Content
            Write-Host "Received command: $commandContent"
            return $commandContent
        } else {
            $errorMessage = "Error retrieving command: $($response.StatusCode) $($response.StatusDescription)"
            Write-Host $errorMessage
            throw $errorMessage
        }
    } catch {
        Write-Host "Error receiving command: $_"
    }
}
# Function to send heartbeat
function Send-Heartbeat {
    param (
        [string]$HashKey
    )

    try {
        $jsonBody = @{
            'hash_key' = $HashKey
        } | ConvertTo-Json

        Write-Host "Sending heartbeat data: $jsonBody"

        $response = Invoke-RestMethod -Uri $HEARTBEAT_URL -Method Post -ContentType "application/json" -Body $jsonBody

        if ($response.StatusCode -eq 200) {
            Write-Host "Heartbeat sent successfully."
        } else {
            $errorMessage = "Failed to send heartbeat: $($response.Content)"
            Write-Host $errorMessage
            throw $errorMessage
        }
    } catch {
        Write-Host "Error sending heartbeat: $_"
    }
}

# Function to send command to server
function Send-Command-To-Server {
    param (
        [string]$CommandUrl,
        [string]$HashKey
    )

    try {
        # Send a request to the server to retrieve the actual command
        $response = Invoke-RestMethod -Uri $CommandUrl -Method Get -ContentType "application/json"

        $command = $response.command

        # Execute the received command
        Write-Host "Executing command: $command"
        Invoke-Expression -Command $command
    } catch {
        Write-Host "Error retrieving or executing command: $_"
    }
}

# Main function
function Main {
    param (
        [Parameter(Mandatory = $true)]
        [string]$HashKey
    )

    Write-Host "Agent script started."

    Register-Agent -HashKey $HashKey

    while ($true) {
        $command = Receive-Command -HashKey $HashKey
        if ($command) {
            # Execute the received command
            Write-Host "Executing command: $command"
            Invoke-Expression -Command $command
        }
        Send-Heartbeat -HashKey $HashKey
        Start-Sleep -Seconds 60  # Send heartbeat every 60 seconds
    }
}

# Call Main function with the hash key argument
Main -HashKey $args[0]