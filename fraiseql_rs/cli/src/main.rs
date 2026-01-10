//! `FraiseQL` Server CLI
//!
//! Standalone GraphQL server binary.

use clap::Parser;

/// `FraiseQL` GraphQL Server
#[derive(Parser, Debug)]
#[command(name = "fraiseql-server")]
#[command(about = "High-performance GraphQL server for `PostgreSQL`")]
#[command(version)]
struct Args {
    /// Host to bind to
    #[arg(short = 'H', long, default_value = "0.0.0.0", env = "FRAISEQL_HOST")]
    host: String,

    /// Port to bind to
    #[arg(short, long, default_value = "8000", env = "FRAISEQL_PORT")]
    port: u16,

    /// `PostgreSQL` connection URL
    #[arg(short, long, env = "DATABASE_URL")]
    database_url: String,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize logging
    tracing_subscriber::fmt::init();

    // Parse CLI arguments
    let args = Args::parse();

    println!("🍓 FraiseQL Server v{}", fraiseql_core::VERSION);
    println!("   Host: {}", args.host);
    println!("   Port: {}", args.port);
    println!(
        "   Database: {}",
        args.database_url.rsplit('@').next().unwrap_or("****")
    );

    // TODO: Initialize and run server
    // let server = fraiseql_core::http::Server::new(config);
    // server.run(&args.host, args.port).await?;

    println!("Server not yet implemented - waiting for core modules");

    Ok(())
}
