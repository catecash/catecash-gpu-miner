use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: catecash-pool-verifier HEADER108 NONCE32 SOLUTION1344");
        std::process::exit(2);
    }
    let parsed = (|| -> Result<bool, Box<dyn std::error::Error>> {
        let header = hex::decode(&args[1])?;
        let nonce = hex::decode(&args[2])?;
        let solution = hex::decode(&args[3])?;
        if header.len() != 108 || nonce.len() != 32 || solution.len() != 1344 {
            return Ok(false);
        }
        Ok(equihash::is_valid_solution(200, 9, &header, &nonce, &solution).is_ok())
    })();
    match parsed {
        Ok(true) => println!("valid"),
        Ok(false) => std::process::exit(1),
        Err(error) => {
            eprintln!("invalid input: {error}");
            std::process::exit(2);
        }
    }
}
