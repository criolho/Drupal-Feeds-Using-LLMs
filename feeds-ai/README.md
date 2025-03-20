# Feeds AI LLM Drupal 10 Demo Project

## Requirements
- PHP 8.1 or higher
- Composer
- MySQL 5.7+ or PostgreSQL 10+
- [DDEV](https://ddev.readthedocs.io/) (optional but recommended)

## Installation

### Using DDEV (Recommended)
```bash
# Clone the repository
git clone https://github.com/criolho/Drupal-Feeds-Using-LLMs.git
cd feeds-ai

# Start DDEV
ddev start

# Install dependencies
ddev composer install

# Install Drupal with existing configuration
ddev drush site:install --existing-config

# OR Import configuration after standard installation
ddev drush site:install
ddev drush config:import
