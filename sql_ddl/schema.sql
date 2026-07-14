CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(30) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
	admin BOOLEAN DEFAULT FALSE NOT NULL,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE groups (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    name VARCHAR(255) UNIQUE NOT NULL,
    description VARCHAR(255) NOT NULL
);

CREATE TABLE objects (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    group_id INT REFERENCES groups(id) ON DELETE CASCADE,
    name VARCHAR(30) NOT NULL UNIQUE,
    description VARCHAR(255) NOT NULL
);

CREATE TABLE absence_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50),
    description VARCHAR(50),
    color VARCHAR(30)
);

CREATE TABLE absences (
    id SERIAL PRIMARY KEY,
    object_id INT REFERENCES objects(id) ON DELETE CASCADE,
    type_id INT REFERENCES absence_types(id) ON DELETE CASCADE,
    abs_date_start DATE NOT NULL,
    abs_date_end DATE NOT NULL,
    description VARCHAR(150)
);

CREATE TABLE user_groups (
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    group_id INT REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, group_id)
);

CREATE TABLE holidays (
    id SERIAL PRIMARY KEY,
    country VARCHAR(4) NOT NULL,
    event_date DATE NOT NULL,
	description VARCHAR(150),
	recurring BOOLEAN DEFAULT False
);